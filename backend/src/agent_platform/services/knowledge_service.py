"""知识库用例（v0.6.1，v0.5 收尾）：上传文件切块 + 关键词检索。

切块：正文按空行分段，段 ≈900 字聚合成块（略大的整段保留整段——段落是语义边界），
      无换行的超长段硬切；单文件上限 400 块。只索引 source=upload 的用户资料。
检索：按指南“先关键词、规模大了再上向量”——查询拆词（纯中文长词再拆 2-gram，常见疑问词过滤），
      LIKE 预取候选块，Python 内按词频与文件名命中打分排序，截取片段返回；
      同一入口同时服务 HTTP 接口与 Agent 的 search_knowledge 工具。
安全：外部资料是**数据**——片段里带不带“指令”都不改变其地位，工具结果文案里也如此提示模型。
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from agent_platform.infrastructure.attachments import extract_text
from agent_platform.repositories.file_assets import FileAssetRepository
from agent_platform.repositories.knowledge import KnowledgeRepository
from agent_platform.services.library_service import LibraryService

CHUNK_TARGET = 900          # 目标块长（字符）
CHUNK_MAX = 400             # 单文件块数上限
CANDIDATE_LIMIT = 400       # 一次检索预取的候选块数
RESULT_LIMIT = 8            # 默认返回条数
SNIPPET_RADIUS = 70         # 片段截取半径
SNIPPET_LIMIT = 260

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


class KnowledgeService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.assets = FileAssetRepository(db)
        self.chunks = KnowledgeRepository(db)
        self.library = LibraryService(db)

    # ---------- 索引 ----------

    def index_asset(self, asset_id: int) -> int | None:
        """重建单文件切块。返回块数；正文提不出来（图片/二进制/已缺失）返回 None。"""
        asset = self.assets.get(asset_id)
        if asset is None:
            return None
        text = extract_text(asset.category, asset.stored_name, asset.content_type)
        if not text:
            return None
        return self.chunks.replace_for_asset(asset, chunk_text(text))

    def auto_index(self, asset_id: int) -> None:
        """上传链路入口：索引失败绝不阻断上传（下次“重建索引”还会补）。"""
        try:
            self.index_asset(asset_id)
        except Exception:  # noqa: BLE001,S110 — 索引失败不阻断上传；重建索引时还会补
            pass

    def reindex_missing(self, user_id: int) -> dict[str, Any]:
        """扫描还没切块（或没切成功过）的上传文件补索引；已切过的不重切。"""
        pending = self.chunks.upload_assets_without_chunks(user_id)
        indexed_assets = total_new = 0
        for asset in pending:
            n = self.index_asset(asset.id)
            if n:
                indexed_assets += 1
                total_new += n
        return {
            "scanned": len(pending),
            "indexed_assets": indexed_assets,
            "new_chunks": total_new,
            "total_chunks": self.chunks.count_for_user(user_id),
        }

    # ---------- 检索 ----------

    def search(
        self, user_id: int, query: str, *, project_id: int | None = None, limit: int = RESULT_LIMIT,
    ) -> dict[str, Any]:
        terms = tokenize_query(query)
        if not terms:
            return {"query": query, "terms": [], "items": []}
        rows = self.chunks.candidates(user_id, terms, project_id=project_id, limit=CANDIDATE_LIMIT)
        scored: list[tuple[int, int, int, Any, Any]] = []
        for chunk, asset in rows:
            body = chunk.content.lower()
            score = 0
            for term in terms:
                count = body.count(term)
                if count:
                    score += min(count, 10) * 2
            name = (asset.filename or "").lower()
            score += sum(3 for term in terms if term in name)
            if score:
                scored.append((-score, chunk.asset_id, chunk.chunk_index, chunk, asset))
        scored.sort()
        items = [
            {
                "asset": self.library.to_out(asset),
                "chunk_index": chunk.chunk_index,
                "snippet": _snippet(chunk.content, terms),
                "score": -neg,
            }
            for neg, _, _, chunk, asset in scored[:limit]
        ]
        return {"query": query, "terms": terms, "items": items}

    def tool_search(self, user_id: int, project_id: int | None, query: str, project_only: bool) -> list[dict[str, Any]]:
        """search_knowledge 工具的闭包入口：project_only 但当前无项目 → 空。"""
        if project_only and project_id is None:
            return []
        scope = project_id if project_only else None
        return self.search(user_id, query, project_id=scope, limit=6)["items"]
