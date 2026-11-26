"""v0.7 隔离测试套件：两个用户 A/B，A 访问 B 的会话/消息/文件/资料库/记忆/设置/检索一律 404 或不可见。

设计文档 3.4 要求：此后凡是新增路由，都要跑这套。用 FastAPI TestClient 走真实 HTTP 层
（身份用依赖覆盖模拟两个登录用户，DB 用 sqlite 内存库，存储落 tmp 目录）。
cloud 模式语义：文件解析不回退根目录、设置走 user_settings 表按用户隔离。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from agent_platform.config import settings
from agent_platform.infrastructure.database.base import Base
from agent_platform.infrastructure.database.models import User
from agent_platform.infrastructure.database.session import get_db
from agent_platform.infrastructure.storage import local as local_storage
from agent_platform.infrastructure.storage.local import LocalStorage
from apps.api.dependencies import get_current_user_id
from apps.api.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """隔离测试环境：两个用户 + HTTP 客户端（auth_mode=cloud 语义）。"""
    monkeypatch.setattr(settings, "auth_mode", "cloud")
    monkeypatch.setattr(settings, "service_secret", "test-service-secret")  # cloud 模式 Key 加密需要
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # TestClient 多线程共享同一内存库
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    user_a = User(username="alice", email="alice@example.com")
    user_b = User(username="bob", email="bob@example.com")
    session.add_all([user_a, user_b])
    session.commit()
    ids = {"a": user_a.id, "b": user_b.id}
    current = {"id": ids["a"]}

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user_id] = lambda: current["id"]
    monkeypatch.setattr(local_storage, "_storage", LocalStorage(tmp_path / "data"))

    # 跳过 lifespan（避免触碰真实 MySQL 的启动维护）
    @asynccontextmanager
    async def noop(_app):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", noop)
    with TestClient(app) as test_client:
        yield test_client, ids, current
    app.dependency_overrides.clear()
    session.close()


def _switch(current: dict, ids: dict, who: str) -> None:
    current["id"] = ids[who]


# ---------- 会话与消息 ----------


def test_conversation_is_hidden_from_other_users(client) -> None:
    tc, ids, current = client
    conv = tc.post("/api/conversations", json={"title": "A 的秘密"}).json()
    assert conv["title"] == "A 的秘密"

    _switch(current, ids, "b")
    # 列表看不见、读消息/改/删/流式续聊全部 404（不暴露存在性）
    listed = tc.get("/api/conversations").json()
    assert all(c["id"] != conv["id"] for c in listed)
    assert tc.get(f"/api/conversations/{conv['id']}/messages").status_code == 404
    assert tc.patch(f"/api/conversations/{conv['id']}", json={"title": "偷改"}).status_code == 404
    assert tc.delete(f"/api/conversations/{conv['id']}").status_code == 404
    assert tc.post("/api/chat/stream", json={"conversation_id": conv["id"], "content": "hi"}).status_code == 404
    assert tc.post(
        "/api/chat/regenerate", json={"conversation_id": conv["id"], "message_id": 1}
    ).status_code == 404

    # 本人照常可读
    _switch(current, ids, "a")
    assert tc.get(f"/api/conversations/{conv['id']}/messages").status_code == 200


def test_other_users_conversation_stream_is_404_not_403(client) -> None:
    """错误码统一 404：不区分'不存在'与'不属于你'，避免暴露资源存在性。"""
    tc, ids, current = client
    conv = tc.post("/api/conversations", json={}).json()
    _switch(current, ids, "b")
    missing = tc.get("/api/conversations/99999/messages")
    foreign = tc.get(f"/api/conversations/{conv['id']}/messages")
    assert missing.status_code == foreign.status_code == 404
    assert missing.json()["detail"] == foreign.json()["detail"]


# ---------- 文件与资料库 ----------


def test_files_and_library_are_scoped_per_user(client) -> None:
    tc, ids, current = client
    upload = tc.post(
        "/api/files",
        files={"file": (" secret.md ", "A 的商业机密".encode("utf-8"), "text/markdown")},
    )
    assert upload.status_code == 201
    body = upload.json()
    asset_id = body["asset_id"]
    url = body["url"]

    _switch(current, ids, "b")
    # 下载：B 拿同一 URL → 定位到 B 的目录 → 404（per-user 目录即归属边界）
    assert tc.get(url).status_code == 404
    # 资料库：列表无此条目；直取/预览/改/删全部 404
    assert all(i["id"] != asset_id for i in tc.get("/api/library/assets").json()["items"])
    assert tc.get(f"/api/library/assets/{asset_id}").status_code == 404
    assert tc.get(f"/api/library/assets/{asset_id}/preview").status_code == 404
    assert tc.patch(f"/api/library/assets/{asset_id}", json={"filename": "偷改.md"}).status_code == 404
    assert tc.delete(f"/api/library/assets/{asset_id}").status_code == 404

    # A 自己仍可下载与预览
    _switch(current, ids, "a")
    got = tc.get(url)
    assert got.status_code == 200 and "A 的商业机密".encode("utf-8") in got.content
    assert tc.get(f"/api/library/assets/{asset_id}").status_code == 200


# ---------- 记忆 ----------


def test_memories_are_scoped_per_user(client) -> None:
    tc, ids, current = client
    mem = tc.post("/api/memories", json={"content": "A 的私人偏好", "scope": "global"}).json()
    _switch(current, ids, "b")
    assert all(m["id"] != mem["id"] for m in tc.get("/api/memories").json())
    assert tc.patch(f"/api/memories/{mem['id']}", json={"enabled": False}).status_code == 404
    assert tc.delete(f"/api/memories/{mem['id']}").status_code == 404


# ---------- 设置（cloud 模式入库隔离）----------


def test_user_settings_are_isolated_in_cloud_mode(client) -> None:
    tc, ids, current = client
    # A 配 DeepSeek Key
    saved = tc.put("/api/settings", json={"provider": "deepseek", "api_key": "sk-alice-only"})
    assert saved.status_code == 200
    assert saved.json()["profiles"]["deepseek"]["has_api_key"] is True

    _switch(current, ids, "b")
    view = tc.get("/api/settings").json()
    assert view["profiles"]["deepseek"]["has_api_key"] is False  # B 看不到 A 的 Key
    assert "sk-alice-only" not in str(view)  # 明文永不回显

    # B 配百炼角色，不影响 A
    tc.put("/api/settings", json={"provider": "qwen", "api_key": "sk-bob-qwen"})
    _switch(current, ids, "a")
    a_view = tc.get("/api/settings").json()
    assert a_view["profiles"]["deepseek"]["has_api_key"] is True
    assert a_view["profiles"]["qwen"]["has_api_key"] is False


# ---------- 知识库检索 ----------


def test_knowledge_search_never_crosses_users(client) -> None:
    tc, ids, current = client
    upload = tc.post(
        "/api/files",
        files={"file": ("量子笔记.md", "量子退相干时间尺度研究".encode("utf-8"), "text/markdown")},
    )
    assert upload.status_code == 201
    _switch(current, ids, "a")
    hits = tc.get("/api/knowledge/search", params={"q": "退相干"}).json()
    assert hits["items"], "本人上传后应能检索到"

    _switch(current, ids, "b")
    foreign = tc.get("/api/knowledge/search", params={"q": "退相干"}).json()
    assert foreign["items"] == []  # B 检索不到 A 的资料


# ---------- 管理员 ----------


def test_admin_surface_forbidden_for_normal_users(client) -> None:
    tc, ids, current = client
    assert tc.get("/api/admin/users").status_code == 403
    assert tc.get("/api/admin/stats").status_code == 403


def test_admin_can_list_disable_and_kick(client, monkeypatch: pytest.MonkeyPatch) -> None:
    tc, ids, current = client
    # 提升用户 A 为管理员
    from agent_platform.repositories.users import UserRepository

    engine_session = app.dependency_overrides[get_db]()
    UserRepository(engine_session).set_status(ids["b"], "active")
    from agent_platform.infrastructure.database.models import User as UserModel

    admin_row = engine_session.get(UserModel, ids["a"])
    admin_row.is_admin = True
    engine_session.commit()

    _switch(current, ids, "a")
    users = tc.get("/api/admin/users").json()
    assert {u["id"] for u in users} >= {ids["a"], ids["b"]}

    stats = tc.get("/api/admin/stats").json()
    assert stats["users_total"] == 2 and "disk_usage" in stats

    # 停用 B
    patched = tc.patch(f"/api/admin/users/{ids['b']}", json={"status": "disabled"})
    assert patched.status_code == 200 and patched.json()["status"] == "disabled"

    # admin 不能停用自己
    assert tc.patch(f"/api/admin/users/{ids['a']}", json={"status": "disabled"}).status_code == 400
    # 非法 status
    assert tc.patch(f"/api/admin/users/{ids['b']}", json={"status": "hacked"}).status_code == 400
