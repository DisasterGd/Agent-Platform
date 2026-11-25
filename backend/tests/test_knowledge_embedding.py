"""v0.6.2 向量检索升级测试：embedding 角色、embed_texts 批量形状、落库与换模型重算、
hybrid 排序、无角色/嵌入失败降级；另含 imagegen DashScope 原生形状适配。

全部离线：网络用 httpx.MockTransport 或 monkeypatch 假 embed_texts，DB 用 sqlite 内存库。
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent_platform.infrastructure import imagegen
from agent_platform.infrastructure.database.base import Base
from agent_platform.infrastructure.database.models import KnowledgeChunk, User
from agent_platform.infrastructure.embeddings import EmbeddingError, embed_texts
from agent_platform.infrastructure.storage import local as local_storage
from agent_platform.infrastructure.storage.local import LocalStorage
from agent_platform.repositories.knowledge import KnowledgeRepository
from agent_platform.services import knowledge_service as ks
from agent_platform.services import settings_service
from agent_platform.services.knowledge_service import KnowledgeService, _cosine
from agent_platform.services.library_service import LibraryService
from agent_platform.services.settings_service import PRESETS, SettingsService

PNG = b"\x89PNG\r\n\x1a\n" + b"pixeldata" * 4


# ---------- 角色与预设 ----------


def test_embedding_preset_lists_and_role_options() -> None:
    assert PRESETS["qwen"]["embedding_models"] == ["text-embedding-v4", "text-embedding-v3"]
    assert PRESETS["zhipu"]["embedding_models"] == ["embedding-3"]
    assert PRESETS["deepseek"]["embedding_models"] == []  # 官方无嵌入端点
    assert settings_service.ROLE_OPTION_KEY["embedding"] == "embedding_models"
    assert "embedding" in settings_service.ROLES


def test_embedding_role_null_on_legacy_derive_and_resolves(tmp_path: Path) -> None:
    svc = SettingsService(tmp_path / "settings.json")
    svc.save({"provider": "qwen", "api_key": "sk-qw",
              "roles": {"reasoning": {"provider": "qwen", "model": "qwen3.7-plus"}}})
    # 模拟没有 roles 键的旧文件：v2 语义派生时 embedding=null，向量检索默认关闭、行为不变
    body = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    del body["roles"]
    (tmp_path / "settings.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    assert svc.roles_view()["embedding"] is None
    assert svc.resolve_role("embedding") is None
    # 配置后解析可用；模型名缺省按预设第一家
    svc.save({"provider": "qwen", "api_key": "sk-qw",
              "roles": {"embedding": {"provider": "qwen"}}})
    resolved = svc.resolve_role("embedding")
    assert resolved is not None and resolved["model"] == "text-embedding-v4"
    assert resolved["api_key"] == "sk-qw"
    # 关掉（null）→ 回到未配置
    svc.save({"provider": "qwen", "roles": {"embedding": None}})
    assert svc.resolve_role("embedding") is None


# ---------- embed_texts（MockTransport，真函数真形状） ----------


def test_embed_batches_by_ten_and_restores_order() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append({"path": request.url.path, "auth": request.headers.get("Authorization", ""),
                     "input": payload["input"]})
        # 故意把 data 顺序打乱并带 index，验证按 index 复位
        items = [{"embedding": [float(len(t)), 1.0], "index": i, "object": "embedding"}
                 for i, t in enumerate(payload["input"])]
        items.reverse()
        return httpx.Response(200, json={"data": items, "model": payload["model"]})

    texts = [f"文本{i}" * (i + 1) for i in range(12)]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        vectors = embed_texts("https://emb.example/v1/", "sk-e", "m1", texts, client=client)
    assert [len(r["input"]) for r in seen] == [10, 2]           # ≤10 条/请求、按输入顺序
    assert seen[0]["path"] == "/v1/embeddings"
    assert seen[0]["auth"] == "Bearer sk-e"
    assert [v[0] for v in vectors] == [float(len(t)) for t in texts]  # 打乱后仍按 index 还原


def test_embed_errors_are_readable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": "Arrearage", "message": "超出配额"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(EmbeddingError, match="超出配额"):  # 原生 {"code","message"} 形状也要读出来
        embed_texts("https://emb.example/v1", "k", "m", ["a"], client=client)

    def short(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [0.1]}]})  # 少给一条

    with httpx.Client(transport=httpx.MockTransport(short)) as client, pytest.raises(EmbeddingError, match="不一致"):
        embed_texts("https://emb.example/v1", "k", "m", ["a", "b"], client=client)

    with pytest.raises(EmbeddingError, match="API Key"):
        embed_texts("https://emb.example/v1", "", "m", ["a"])

    assert embed_texts("https://emb.example/v1", "k", "m", []) == []


# ---------- _cosine 纯函数 ----------


def test_cosine_basic() -> None:
    assert math.isclose(_cosine([1, 0], [3, 0]), 1.0)
    assert math.isclose(_cosine([1, 0], [0, 5]), 0.0)
    assert _cosine([0, 0], [1, 1]) == 0.0  # 零向量安全


# ---------- 索引与向量落库（sqlite + 假 embed_texts） ----------


@pytest.fixture()
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """内存库 + 临时存储 + 临时设置（qwen 已配 embedding 角色）+ KnowledgeService。"""
    monkeypatch.setattr(local_storage, "_storage", LocalStorage(tmp_path))
    svc = SettingsService(tmp_path / "settings.json")
    monkeypatch.setattr(settings_service, "_service", svc)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    user = User(username="tester")
    db.add(user)
    db.commit()
    svc.save({"provider": "qwen", "api_key": "sk-qw",
              "roles": {"reasoning": {"provider": "qwen"},
                        "embedding": {"provider": "qwen", "model": "emb-a"}}})
    yield db, user.id, svc, KnowledgeService(db)
    db.close()


def _register(db: Session, storage_dir: Path, user_id: int, name: str, content: str) -> int:
    stored = LocalStorage(storage_dir).save(
        category="uploads", filename=name, content=content.encode("utf-8"),
        content_type="text/markdown")
    asset = LibraryService(db).register_saved(stored, user_id=user_id, source="upload")
    return int(asset["id"])


def test_index_asset_embeds_and_model_switch_recomputes(world, tmp_path: Path, monkeypatch) -> None:
    db, uid, svc, ksvc = world
    calls: list[list[str]] = []

    def fake_embed(base_url: str, api_key: str, model: str, texts, *, client=None):
        calls.append(list(texts))
        return [[float(len(t)) * 0.01, 1.0] for t in texts]

    monkeypatch.setattr(ks, "embed_texts", fake_embed)
    asset_id = _register(db, tmp_path, uid, "笔记.md", "量子计算\n\n退相干时间尺度\n\n贝尔不等式")
    n = ksvc.index_asset(asset_id)
    assert n == 1  # 三段短句聚合成一块（≤900 字）
    assert len(calls) == 1 and calls[0] == ["量子计算\n\n退相干时间尺度\n\n贝尔不等式"]
    chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.asset_id == asset_id).all()
    assert all(c.embedding and c.embedding_model == "emb-a" for c in chunks)

    # 再跑一次 reindex：块没缺、模型没换 → 不重复嵌入（幂等、不浪费配额）
    calls.clear()
    stats = ksvc.reindex_missing(uid)
    assert calls == [] and stats["embedded_chunks"] == 0
    assert stats["total_chunks"] == 1  # 旧统计键原样保留

    # 换嵌入模型＝旧向量作废，重建索引整体重算
    svc.save({"provider": "qwen", "roles": {"embedding": {"provider": "qwen", "model": "emb-b"}}})
    stats = ksvc.reindex_missing(uid)
    assert stats["embedded_chunks"] == len(chunks)
    db.expire_all()
    rows = db.query(KnowledgeChunk).filter(KnowledgeChunk.asset_id == asset_id).all()
    assert all(r.embedding_model == "emb-b" for r in rows)


def test_embed_failure_never_breaks_chunking(world, tmp_path: Path, monkeypatch) -> None:
    db, uid, _svc, ksvc = world

    def boom(base_url, api_key, model, texts, *, client=None):
        raise EmbeddingError("HTTP 429：限流")

    monkeypatch.setattr(ks, "embed_texts", boom)
    asset_id = _register(db, tmp_path, uid, "降级.md", "第一段内容\n\n第二段内容")
    n = ksvc.index_asset(asset_id)
    assert n == 1  # 切块照常成功
    chunks = db.query(KnowledgeChunk).filter(KnowledgeChunk.asset_id == asset_id).all()
    assert all(c.embedding is None and c.embedding_model == "" for c in chunks)
    stats = ksvc.reindex_missing(uid)
    assert stats["embedded_chunks"] == 0  # 嵌入坏着也只是不补，不炸


# ---------- 回归：历史扫描登记的上传文件（source=library）必须可索引、可检索 ----------


def test_legacy_scanned_uploads_are_indexed_and_searchable(world, tmp_path: Path, monkeypatch) -> None:
    """v0.6.1 曾按 source=upload 筛选，v0.5 前上传、后被扫描登记（source=library）的老文件永远漏网——
    判据改为 category=uploads 后两种登记方式都覆盖；生成物（category=generated）依旧排除。"""
    db, uid, _svc, ksvc = world
    monkeypatch.setattr(ks, "embed_texts", lambda *a, **k: [[1.0, 0.0]] * len(a[3]))
    stored = LocalStorage(tmp_path).save(
        category="uploads", filename="历史笔记.md",
        content="栈的入栈出栈规则\n\n递归与栈的协作".encode(), content_type="text/markdown")
    asset = LibraryService(db).register_saved(stored, user_id=uid, source="library")  # 扫描登记路径
    stats = ksvc.reindex_missing(uid)
    assert stats["indexed_assets"] == 1 and stats["new_chunks"] >= 1
    hits = ksvc.search(uid, "栈")
    assert hits["items"] and hits["items"][0]["asset"]["id"] == int(asset["id"])
    assert int(asset["id"]) in {c[1] for c in ksvc.chunks.vectors_for_user(uid, "emb-a")}  # 语义通道同口径


# ---------- hybrid 排序与降级 ----------

Q = "量子 退相干"
# 块内容以两位标记开头，假嵌入按标记查表（查询文本用 Q 精确匹配）
TEXTS = {
    "量子笔记.md": "AA 量子 量子 量子 退相干 退相干 退相干",   # 词面强命中，cos=0.6
    "披萨地理.md": "BB 凤梨与披萨在意大利的饮食争议",            # 词面 0 命中，cos=0.98
    "混合信号.md": "CC 这里只提到量子一次",                      # 词面弱命中，cos=0.5
    "词面命中.md": "DD 退相干 的另一种写法",                     # 词面弱命中，cos=0
    "气象手册.md": "EE 热带气旋的命名规则",                      # 词面 0 命中，cos=0.30 < SEM_MIN
}
VECS = {
    Q: [1.0, 0.0],
    "AA": [0.6, 0.8],
    "BB": [0.98, 0.199],
    "CC": [0.5, 0.866],
    "DD": [0.0, 1.0],
    "EE": [0.30, 0.9539],
}


def _fake_embed(base_url, api_key, model, texts, *, client=None):
    return [VECS[t] if t == Q else VECS[t[:2]] for t in texts]


def _seed(db: Session, tmp_path: Path, uid: int, ksvc: KnowledgeService, names: list[str]) -> None:
    for name in names:
        ksvc.index_asset(_register(db, tmp_path, uid, name, TEXTS[name]))


def test_hybrid_recalls_semantic_only_and_fuses_ranking(world, tmp_path: Path, monkeypatch) -> None:
    db, uid, _svc, ksvc = world
    monkeypatch.setattr(ks, "embed_texts", _fake_embed)
    _seed(db, tmp_path, uid, ksvc, list(TEXTS))
    res = ksvc.search(uid, Q, limit=8)
    order = [i["asset"]["filename"] for i in res["items"]]
    # A 词面最强 +0.6 语义；B 纯语义召回（score=0）超过 C 词面弱命中；E 低于噪声线不出现
    assert order == ["量子笔记.md", "披萨地理.md", "混合信号.md", "词面命中.md"]
    a, b, c, d = res["items"]
    assert a["score"] == 15 and b["score"] == 0 and c["score"] == 2 and d["score"] == 2  # 关键词分口径不变
    assert a["semantic"] == {"vector": 0.6, "final": 0.76}  # 0.4×1 + 0.6×0.6
    assert b["semantic"]["vector"] == 0.98                  # 0.6×0.98=0.588 → 第二
    assert d["semantic"]["vector"] is None                  # cos=0 视为无向量，诊断字段留 null
    # 语义召回块的片段仍可回捞（rows_by_ids 补取的行有正文）
    assert "凤梨" in b["snippet"]


def test_pure_semantic_below_gate_excluded(world, tmp_path: Path, monkeypatch) -> None:
    """cos 低于 SEM_MIN（真实标定：无关文本 ≈0.15~0.33）且词面 0 命中 → 不该混进结果。"""
    db, uid, _svc, ksvc = world
    monkeypatch.setattr(ks, "embed_texts", _fake_embed)
    _seed(db, tmp_path, uid, ksvc, ["量子笔记.md", "气象手册.md"])
    res = ksvc.search(uid, Q)
    assert [i["asset"]["filename"] for i in res["items"]] == ["量子笔记.md"]


def test_hybrid_off_matches_legacy_keyword_order(world, tmp_path: Path, monkeypatch) -> None:
    """角色关闭时的排序与 v0.6.1 纯关键词一致（0.4×归一分单调），语义路完全不走。"""
    db, uid, svc, ksvc = world
    monkeypatch.setattr(ks, "embed_texts", _fake_embed)
    _seed(db, tmp_path, uid, ksvc, list(TEXTS))
    svc.save({"provider": "qwen", "roles": {"embedding": None}})
    calls: list = []
    monkeypatch.setattr(ks, "embed_texts", lambda *a, **k: calls.append(a))
    res = ksvc.search(uid, Q)
    assert calls == []  # 没角色一次都不调嵌入
    assert [i["asset"]["filename"] for i in res["items"]] == ["量子笔记.md", "混合信号.md", "词面命中.md"]
    assert all(i["semantic"] is None for i in res["items"])


def test_degrade_on_query_embed_failure(world, tmp_path: Path, monkeypatch) -> None:
    """角色开着但查询嵌入失败 → 静默降级纯关键词（已存向量不参与也不报错）。"""
    db, uid, _svc, ksvc = world
    monkeypatch.setattr(ks, "embed_texts", _fake_embed)
    _seed(db, tmp_path, uid, ksvc, list(TEXTS))

    def boom(base_url, api_key, model, texts, *, client=None):
        raise EmbeddingError("连不上")

    monkeypatch.setattr(ks, "embed_texts", boom)
    res = ksvc.search(uid, Q)
    assert [i["asset"]["filename"] for i in res["items"]] == ["量子笔记.md", "混合信号.md", "词面命中.md"]
    assert all(i["semantic"] is None for i in res["items"])


def test_dimension_mismatch_vectors_are_skipped(world, tmp_path: Path, monkeypatch) -> None:
    """同名模型下的 3 维脏向量：不可比 → 跳过，不影响其他候选的语义分。"""
    db, uid, _svc, ksvc = world
    monkeypatch.setattr(ks, "embed_texts", _fake_embed)
    _seed(db, tmp_path, uid, ksvc, ["量子笔记.md", "披萨地理.md"])
    repo = KnowledgeRepository(db)
    bad_ids = [cid for (cid,) in db.query(KnowledgeChunk.id).filter(
        KnowledgeChunk.content.like("BB%")).all()]
    repo.set_embeddings([(cid, [0.9, 0.1, 0.4]) for cid in bad_ids], "emb-a")
    res = ksvc.search(uid, Q)
    names = [i["asset"]["filename"] for i in res["items"]]
    assert names == ["量子笔记.md"]  # 语义-only 的 BB 因维度脏数据被排除


# ---------- imagegen：DashScope 原生形状（v0.6.2 适配） ----------


def _run_gen(base_url: str, handler) -> tuple[bytes, str]:
    async def go():
        saved = imagegen.TASK_POLL_INTERVAL_SECONDS
        imagegen.TASK_POLL_INTERVAL_SECONDS = 0.0
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await imagegen.generate_image(
                    base_url, "sk-x", "qwen-image-2.0-pro", "橘猫宇航员", client=client)
        finally:
            imagegen.TASK_POLL_INTERVAL_SECONDS = saved
    return asyncio.run(go())


DASHSCOPE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_imagegen_dashscope_native_sync_shape() -> None:
    """实测形状：compatible-mode 无 /images/generations（404），原生 multimodal-generation 同步出图。"""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={
                "output": {"choices": [{"message": {"role": "assistant",
                                                    "content": [{"image": "https://cdn.example/a.png",
                                                                 "type": "image"}]}}]},
                "usage": {"width": 1024, "height": 1024, "image_count": 1},
            })
        assert str(request.url) == "https://cdn.example/a.png"
        return httpx.Response(200, content=PNG)

    data, mime = _run_gen(DASHSCOPE, handler)
    assert data == PNG and mime == "image/png"
    assert seen["path"] == "/api/v1/services/aigc/multimodal-generation/generation"  # 绕开了 404 的 compatible-mode
    assert seen["body"]["input"]["messages"][0]["content"][0]["text"] == "橘猫宇航员"
    assert seen["body"]["parameters"]["size"] == "1024*1024"  # 原生是 W*H 星号


def test_imagegen_dashscope_native_async_task() -> None:
    """某些模型只给 task_id（text2image 系）→ 轮询 /api/v1/tasks/{id} 直到 SUCCEEDED。"""
    state = {"polls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"output": {"task_id": "t-1", "task_status": "PENDING"}})
        if request.url.path == "/api/v1/tasks/t-1":
            state["polls"] += 1
            if state["polls"] == 1:
                return httpx.Response(200, json={"output": {"task_id": "t-1", "task_status": "RUNNING"}})
            return httpx.Response(200, json={"output": {
                "task_status": "SUCCEEDED", "results": [{"url": "https://cdn.example/b.png"}]}})
        assert str(request.url) == "https://cdn.example/b.png"
        return httpx.Response(200, content=PNG)

    data, mime = _run_gen(DASHSCOPE, handler)
    assert data == PNG and mime == "image/png" and state["polls"] == 2


def test_imagegen_dashscope_task_failed_surfaces_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"output": {"task_id": "t-2"}})
        return httpx.Response(200, json={"output": {"task_status": "FAILED",
                                                    "code": "IPInfringementSuspect",
                                                    "message": "内容涉嫌侵权"}})

    with pytest.raises(imagegen.ImageGenError, match="涉嫌侵权"):
        _run_gen(DASHSCOPE, handler)


def test_imagegen_native_error_shape_in_brief() -> None:
    """厂商报 {"code","message"}（无 OpenAI error 键）时，错误文本不能是空 body。"""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": "InvalidParameter", "message": "url error"})

    with pytest.raises(imagegen.ImageGenError, match="url error"):
        _run_gen(DASHSCOPE, handler)


def test_imagegen_openai_shape_first_for_generic_vendors() -> None:
    """非 DashScope 厂商：保持 OpenAI /images/generations 原形状（智谱 glm-image 等）。"""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/paas/v4/images/generations"
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})

    data, mime = _run_gen("https://open.bigmodel.cn/api/paas/v4/", handler)
    assert data == PNG and mime == "image/png"


def test_origin_helper_strips_path() -> None:
    assert imagegen._origin(DASHSCOPE) == "https://dashscope.aliyuncs.com"
    assert imagegen._origin("https://dashscope.aliyuncs.com") == "https://dashscope.aliyuncs.com"
