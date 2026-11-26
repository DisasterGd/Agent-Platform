"""知识库用例（v0.6.1 切块 + 关键词检索；v0.6.2 起 hybrid 语义混排）。

切块：正文按空行分段，段 ≈900 字聚合成块（略大的整段保留整段——段落是语义边界），
      无换行的超长段硬切；单文件上限 400 块。只索引 source=upload 的用户资料。
检索：按指南“先关键词、规模大了再上向量”——查询拆词（纯中文长词再拆 2-gram，常见疑问词过滤），
      LIKE 预取候选块，Python 内按词频与文件名命中打分排序，截取片段返回；
      **v0.6.2**：嵌入角色可用时把查询嵌入一次，对全库候选向量算 cosine，与关键词分加权融合
      （final = 0.4*keyword_norm + 0.6*cosine，理由见 W_KEYWORD/W_SEMANTIC 注释）；
      角色未配置 / 嵌入失败 → 静默降级纯关键词，响应结构与 v0.6.1 向后兼容（semantic 字段为 null）。
同一入口同时服务 HTTP 接口与 Agent 的 search_knowledge 工具。
安全：外部资料是**数据**——片段里带不带“指令”都不改变其地位，工具结果文案里也如此提示模型。
"""
from __future__ import annotations

import math
import re
from typing import Any

from sqlalchemy.orm import Session

from agent_platform.infrastructure.attachments import extract_text
from agent_platform.infrastructure.embeddings import embed_texts
from agent_platform.repositories.file_assets import FileAssetRepository
from agent_platform.repositories.knowledge import KnowledgeRepository
from agent_platform.services.library_service import LibraryService
from agent_platform.services.settings_service import (
    get_settings_service,
    user_settings_service,
)

CHUNK_TARGET = 900          # 目标块长（字符）
CHUNK_MAX = 400             # 单文件块数上限
CANDIDATE_LIMIT = 400       # 一次检索预取的候选块数
RESULT_LIMIT = 8            # 默认返回条数
SNIPPET_RADIUS = 70         # 片段截取半径
SNIPPET_LIMIT = 260

# ---------- hybrid 权重（v0.6.2 向量检索升级） ----------
#: final = W_KEYWORD × 关键词归一分 + W_SEMANTIC × cosine（clamp 到 [0,1]）。
#: 语义权重更高：本次升级的收益主要在“意思相近但用词不同”的召回；
#: 关键词分经 min-max 归一后最强命中即 1，精确词（代码符号、专名）仍被词频×文件名放大，
#: 单纯词面强命中（0.4）通常压过中等相似（0.6×0.6≈0.36）——两路信号互不霸占、又都能上浮。
W_KEYWORD = 0.4
W_SEMANTIC = 0.6
#: 关键词未命中的块要进候选，cosine 至少到这个线。按 2026-11 对 DashScope text-embedding-v4
#: 的实测标定：无关中文文本对 cos≈0.15~0.33，同主题对 ≈0.82 —— 0.35 切在噪声带上沿，给“换说法”留余量。
SEM_MIN = 0.35
#: 每次检索最多补进多少个“无语面命中、纯语义”的候选块（片段内容按需回捞，避免拉全库正文）
SEM_EXTRA = 32

_PARA_SPLIT = re.compile(r"\n[ \t]*\n+")
_TERM_SPLIT = re.compile(r"[^0-9A-Za-z_一-鿿]+")
_CJK_ONLY = re.compile(r"[一-鿿]+")
#: 中文疑问/口语碎词：2-gram 拆出来没有检索价值
_STOPWORDS = {"什么", "怎么", "如何", "哪些", "为什么", "请问", "帮我", "介绍", "一下", "可以", "这个", "那个", "以及", "讲讲", "看看", "是不是"}


def chunk_text(text: str, *, target: int = CHUNK_TARGET, max_chunks: int = CHUNK_MAX) -> list[str]:
    """纯函数：把长文本切成检索块。"""
    norm = re.sub(r"\r\n?", "\n", text or "").strip()
    if not norm:
        return []
    parts: list[str] = []
    for para in _PARA_SPLIT.split(norm):
        para = para.strip()
        if not para:
            continue
        if len(para) <= target * 2:
            parts.append(para)
            continue
        buf = ""
        for line in para.split("\n"):
            if not buf:
                buf = line
            elif len(buf) + 1 + len(line) <= target:
                buf += "\n" + line
            else:
                parts.append(buf)
                buf = line
        if buf:
            parts.append(buf)
    chunks: list[str] = []
    buf = ""
    for part in parts:
        if not buf:
            buf = part
        elif len(buf) + 2 + len(part) <= target:
            buf = f"{buf}\n\n{part}"
        else:
            chunks.append(buf.strip())
            buf = part
        while len(buf) > target * 2:  # 无换行的超长段 → 硬切
            chunks.append(buf[:target].strip())
            buf = buf[target:]
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if c][:max_chunks]


def tokenize_query(query: str) -> list[str]:
    """纯函数：查询 → 检索词（中文长串拆 2-gram，过滤疑问碎词，上限 12）。"""
    terms: list[str] = []

    def add(term: str) -> None:
        if term and term not in _STOPWORDS and term not in terms and len(terms) < 12:
            terms.append(term)

    for raw in _TERM_SPLIT.split((query or "").lower()):
        token = raw.strip()
        if not token:
            continue
        if _CJK_ONLY.fullmatch(token) and len(token) > 3:
            for i in range(len(token) - 1):
                add(token[i : i + 2])
        else:
            add(token)
    return terms


def _snippet(content: str, terms: list[str]) -> str:
    lowered = content.lower()
    pos = -1
    for term in terms:
        found = lowered.find(term)
        if found >= 0 and (pos < 0 or found < pos):
            pos = found
    if pos < 0:
        head = content[:SNIPPET_LIMIT].strip()
        return head + ("…" if len(content) > len(head) else "")
    start = max(0, pos - SNIPPET_RADIUS)
    end = min(len(content), pos + SNIPPET_RADIUS + 80)
    text = content[start:end].strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(content) else ""
    return f"{prefix}{text}{suffix}"


def _keyword_score(chunk: Any, asset: Any, terms: list[str]) -> int:
    """关键词打分（与 v0.6.1 完全一致）：块内词频×2（单词封顶 10）+ 文件名命中×3。"""
    body = chunk.content.lower()
    score = 0
    for term in terms:
        count = body.count(term)
        if count:
            score += min(count, 10) * 2
    name = (asset.filename or "").lower()
    score += sum(3 for term in terms if term in name)
    return score


def _cosine(a: list[float], b: list[float]) -> float:
    """纯 Python cosine（不引 numpy：本地规模数千~数万块，全量点积一次毫秒级）。

    维度不同的向量不可比——调用方负责先按嵌入模型名过滤，再校验长度。
    """
    dot = na = nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


class KnowledgeService:
    def __init__(
        self, db: Session, user_id: int | None = None, settings_service=None
    ) -> None:
        self.db = db
        self.assets = FileAssetRepository(db)
        self.chunks = KnowledgeRepository(db)
        self.library = LibraryService(db)
        # v0.7：嵌入角色配置按用户解析（cloud=各用户各凭据；None → 共享文件，行为同 v0.6，测试可注入）
        if settings_service is not None:
            self._settings = settings_service
        elif user_id is None:
            self._settings = get_settings_service()
        else:
            self._settings = user_settings_service(db, user_id)

    # ---------- 索引 ----------

    def index_asset(self, asset_id: int) -> int | None:
        """重建单文件切块。返回块数；正文提不出来（图片/二进制/已缺失）返回 None。

        切块成功后，嵌入角色可用则顺手补上向量（v0.6.2）；嵌入失败绝不影响切块——
        块保持有效、向量列为空，后续“重建索引”还会补。
        """
        asset = self.assets.get(asset_id)
        if asset is None:
            return None
        text = extract_text(asset.category, asset.stored_name, asset.content_type, asset.user_id)
        if not text:
            return None
        n = self.chunks.replace_for_asset(asset, chunk_text(text))
        try:
            self._embed_pending(asset_id=asset_id)
        except Exception:  # noqa: BLE001,S110 — 嵌入失败不阻断切块；重建索引时还会补
            pass
        return n

    def auto_index(self, asset_id: int) -> None:
        """上传链路入口：索引失败绝不阻断上传（下次“重建索引”还会补）。"""
        try:
            self.index_asset(asset_id)
        except Exception:  # noqa: BLE001,S110 — 索引失败不阻断上传；重建索引时还会补
            pass

    def reindex_missing(self, user_id: int) -> dict[str, Any]:
        """扫描还没切块（或没切成功过）的上传文件补索引；已切过的不重切。

        v0.6.2：嵌入角色可用时，另外补“已有块但缺向量 / 向量出自别的模型”的块——
        换嵌入模型＝旧向量不可比，这里整体重算。角色关闭时 embedded_chunks 恒为 0，行为同 v0.6.1。
        """
        pending = self.chunks.upload_assets_without_chunks(user_id)
        indexed_assets = total_new = 0
        for asset in pending:
            n = self.index_asset(asset.id)
            if n:
                indexed_assets += 1
                total_new += n
        embedded = 0
        try:
            embedded = self._embed_pending(user_id=user_id)
        except Exception:  # noqa: BLE001,S110 — 补向量失败不影响切块统计返回
            pass
        return {
            "scanned": len(pending),
            "indexed_assets": indexed_assets,
            "new_chunks": total_new,
            "total_chunks": self.chunks.count_for_user(user_id),
            "embedded_chunks": embedded,
        }

    # ---------- 嵌入（v0.6.2：嵌入角色缺失/失败一律静默降级） ----------

    def _embedding_role(self) -> dict | None:
        """嵌入角色配置；未配置、无模型名或该供应商没 Key → None（关闭向量检索）。"""
        cfg = self._settings.resolve_role("embedding")
        if not cfg or not str(cfg.get("api_key") or "").strip():
            return None
        return cfg

    def _embed(self, role: dict, texts: list[str]) -> list[list[float]] | None:
        """调一次批量嵌入（内部按 ≤10 条分批、顺序请求）；任何失败返回 None，由调用方降级。"""
        if not texts:
            return []
        try:
            return embed_texts(role["base_url"], role["api_key"], role["model"], texts)
        except Exception:  # noqa: BLE001 — 嵌入失败不能让索引/检索链路报错
            return None

    def _embed_pending(self, *, asset_id: int | None = None, user_id: int | None = None) -> int:
        """给“没向量或向量模型不符”的块补嵌入并落库，返回本轮写入的块数。

        中途失败＝本轮不写（块向量保持缺失），下次重建索引继续补；不做跨请求断点续传，本地规模够用。
        """
        role = self._embedding_role()
        if role is None:
            return 0
        pending = self.chunks.chunks_without_vectors(role["model"], user_id=user_id, asset_id=asset_id)
        if not pending:
            return 0
        vectors = self._embed(role, [c.content for c in pending])
        if not vectors or len(vectors) != len(pending):
            return 0
        model_name = str(role["model"])
        return self.chunks.set_embeddings(
            [(c.id, v) for c, v in zip(pending, vectors, strict=True)], model_name,
        )

    # ---------- 检索 ----------

    def search(
        self, user_id: int, query: str, *, project_id: int | None = None, limit: int = RESULT_LIMIT,
    ) -> dict[str, Any]:
        """hybrid 检索：关键词分（v0.6.1 口径不变）+ 语义 cosine 加权融合。

        嵌入角色不可用 / 查询嵌入失败时 hybrid=False，排序与响应和 v0.6.1 完全一致
        （items 多出恒为 null 的 semantic 字段，向后兼容）。
        """
        terms = tokenize_query(query)
        if not terms:
            return {"query": query, "terms": [], "items": []}
        rows = self.chunks.candidates(user_id, terms, project_id=project_id, limit=CANDIDATE_LIMIT)
        kw_scores: dict[int, int] = {}
        chunk_rows: dict[int, tuple[Any, Any]] = {}
        for chunk, asset in rows:
            score = _keyword_score(chunk, asset, terms)
            if score:
                kw_scores[chunk.id] = score
                chunk_rows[chunk.id] = (chunk, asset)
        kw_max = max(kw_scores.values(), default=0)

        # ---- 语义路（v0.6.2）----
        cos_by_id: dict[int, float] = {}
        hybrid = False
        role = self._embedding_role()
        if role is not None:
            qvecs = self._embed(role, [query.strip()])
            if qvecs and qvecs[0]:
                qvec = qvecs[0]
                for cid, _aid, _idx, vec in self.chunks.vectors_for_user(
                    user_id, str(role["model"]), project_id=project_id,
                ):
                    if len(vec) != len(qvec):
                        continue  # 同名模型下的脏数据（维度不符）：不可比，跳过
                    cos = _cosine(qvec, vec)
                    if cos > 0.0:
                        cos_by_id[cid] = min(1.0, cos)
                hybrid = True
                # 词面完全没命中、但语义足够近的块也进候选——这正是向量升级要解决的
                extras = sorted(
                    ((cid, c) for cid, c in cos_by_id.items() if cid not in chunk_rows and c >= SEM_MIN),
                    key=lambda kv: -kv[1],
                )[:SEM_EXTRA]
                if extras:
                    for chunk, asset in self.chunks.rows_by_ids([cid for cid, _ in extras]):
                        chunk_rows.setdefault(chunk.id, (chunk, asset))

        scored: list[tuple[float, int, int, Any, Any]] = []
        for cid, (chunk, asset) in chunk_rows.items():
            kw = kw_scores.get(cid, 0)  # 语义-only 候选没有关键词分
            kw_norm = kw / kw_max if kw_max else 0.0
            final = W_KEYWORD * kw_norm + W_SEMANTIC * cos_by_id.get(cid, 0.0)
            if final <= 0.0:
                continue
            scored.append((final, chunk.asset_id, chunk.chunk_index, chunk, asset))
        # hybrid 关闭时 sem 恒 0、final 与关键词分单调同序 → 排序结果与 v0.6.1 一致
        scored.sort(key=lambda t: (-t[0], t[1], t[2]))
        items = []
        for final, _, _, chunk, asset in scored[:limit]:
            vec_cos = cos_by_id.get(chunk.id)
            items.append({
                "asset": self.library.to_out(asset),
                "chunk_index": chunk.chunk_index,
                "snippet": _snippet(chunk.content, terms),
                # score 保持“原关键词分”口径（前端展示/诊断），排序已改用 hybrid final
                "score": kw_scores.get(chunk.id, 0),
                "semantic": None if not hybrid else {
                    "vector": round(vec_cos, 4) if vec_cos is not None else None,
                    "final": round(final, 4),
                },
            })
        return {"query": query, "terms": terms, "items": items}

    def tool_search(self, user_id: int, project_id: int | None, query: str, project_only: bool) -> list[dict[str, Any]]:
        """search_knowledge 工具的闭包入口：project_only 但当前无项目 → 空。"""
        if project_only and project_id is None:
            return []
        scope = project_id if project_only else None
        return self.search(user_id, query, project_id=scope, limit=6)["items"]
