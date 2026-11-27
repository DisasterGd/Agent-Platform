"""v0.8.0 平台配置测试：邮件/搜索的部署级存储（加密落库、永不回显、.env 回退、写权限门禁、实时生效）。

验收（设计文档 0.8.x）：部署者在设置页填 SMTP 并测试发送成功，全程不改文件、不重启；非 admin 不可见。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent_platform.config import settings
from agent_platform.infrastructure import secret_store
from agent_platform.infrastructure.database.base import Base
from agent_platform.infrastructure.database.models import User
from agent_platform.infrastructure.database.session import get_db
from agent_platform.infrastructure.mail import factory as mail_factory
from agent_platform.infrastructure.mail.smtp import SMTPProvider
from agent_platform.infrastructure.search import factory as search_factory
from agent_platform.services import platform_settings
from apps.api.dependencies import get_current_user_id
from apps.api.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """local 模式测试环境 + sqlite 内存库（同既有惯例）。"""
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_user", "")
    monkeypatch.setattr(settings, "smtp_password", "")
    monkeypatch.setattr(settings, "mail_from", "")
    monkeypatch.setattr(settings, "search_api_key", "")
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    admin = User(username="dev")
    other = User(username="other", email="other@example.com")
    session.add_all([admin, other])
    session.commit()
    ids = {"a": admin.id, "b": other.id}
    current = {"id": ids["a"]}

    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user_id] = lambda: current["id"]

    @asynccontextmanager
    async def noop(_app):
        yield

    monkeypatch.setattr(app.router, "lifespan_context", noop)
    with TestClient(app) as tc:
        yield tc, session, ids, current
    app.dependency_overrides.clear()
    session.close()


# ---------- 配置解析：加密落库 + .env 回退 ----------


def test_mail_config_roundtrip_and_encryption(client) -> None:
    tc, db, _ids, _current = client
    view = platform_settings.save_mail_config(db, {
        "provider": "smtp", "host": "smtp.qq.com", "port": 465,
        "user": "me@qq.com", "password": "auth-code-123", "from_addr": "me@qq.com",
    })
    assert view["provider"] == "smtp" and view["has_password"] is True and view["smtp_complete"] is True
    # 密文落库：库里不含明文
    stored = platform_settings.DeploymentSettingsRepository(db).get("mail")
    assert stored["password_enc"].startswith(("enc:v1:", "enc:f1:")) and "auth-code-123" not in str(stored)
    # 解密后工厂组装出 SMTPProvider 且参数就位（实时解析，无需重启）
    provider = platform_settings.get_mail_provider(db)
    assert isinstance(provider, SMTPProvider) and provider.user == "me@qq.com" and provider.password == "auth-code-123"


def test_mail_config_falls_back_to_env(client, monkeypatch: pytest.MonkeyPatch) -> None:
    tc, db, _ids, _current = client
    monkeypatch.setattr(settings, "smtp_host", "env-host.example.com")
    monkeypatch.setattr(settings, "smtp_user", "env-user@example.com")
    # 未在界面保存任何东西 → 全 .env 回退
    view = platform_settings.mail_config_view(db)
    assert view["host"] == "env-host.example.com" and view["user"] == "env-user@example.com"
    # 界面只覆盖一个字段：其余仍回退 .env
    platform_settings.save_mail_config(db, {"host": "ui-host.example.com"})
    view2 = platform_settings.mail_config_view(db)
    assert view2["host"] == "ui-host.example.com" and view2["user"] == "env-user@example.com"


def test_mail_password_semantics_keep_clear_replace(client) -> None:
    tc, db, _ids, _current = client
    platform_settings.save_mail_config(db, {"provider": "smtp", "host": "h", "user": "u", "password": "v1"})
    assert platform_settings.mail_config_view(db)["has_password"] is True
    # 缺省=保留
    platform_settings.save_mail_config(db, {"host": "h2"})
    assert platform_settings.mail_config_view(db)["has_password"] is True
    # 空串=清除
    platform_settings.save_mail_config(db, {"password": ""})
    assert platform_settings.mail_config_view(db)["has_password"] is False
    # 非空=替换
    platform_settings.save_mail_config(db, {"password": "v2"})
    assert platform_settings.get_mail_provider(db).password == "v2"


def test_search_config_roundtrip_and_encryption(client) -> None:
    tc, db, _ids, _current = client
    view = platform_settings.save_search_config(db, {"provider": "tavily", "api_key": "tvly-abc"})
    assert view["provider"] == "tavily" and view["has_api_key"] is True
    provider = search_factory.create_search_provider(db)
    assert type(provider).__name__ == "TavilySearchProvider"
    # 库里无明文
    stored = platform_settings.DeploymentSettingsRepository(db).get("search")
    assert "tvly-abc" not in str(stored)
    # 未配置 Key 的 tavily → 如实报错（错误信息指向设置页）
    platform_settings.save_search_config(db, {"api_key": ""})
    with pytest.raises(search_factory.SearchUnavailableError, match="设置"):
        search_factory.create_search_provider(db)


def test_mail_factory_without_db_uses_env(client, monkeypatch: pytest.MonkeyPatch) -> None:
    tc, db, _ids, _current = client
    monkeypatch.setattr(settings, "mail_provider", "console")
    assert mail_factory.get_mail_provider(None).channel == "console"
    monkeypatch.setattr(settings, "mail_provider", "smtp")
    monkeypatch.setattr(settings, "smtp_host", "smtp.qq.com")
    monkeypatch.setattr(settings, "smtp_user", "u@qq.com")
    monkeypatch.setattr(settings, "smtp_password", "p")
    assert mail_factory.get_mail_provider(None).channel == "smtp"


# ---------- HTTP 层：门禁 + 语义 + 测试发送 ----------


def test_mail_endpoints_and_gate(client, monkeypatch: pytest.MonkeyPatch) -> None:
    tc, db, ids, current = client
    # local 模式：本机用户即管理员
    assert tc.get("/api/admin/settings/mail").status_code == 200
    saved = tc.put("/api/admin/settings/mail", json={
        "provider": "smtp", "host": "smtp.qq.com", "port": 465, "user": "me@qq.com", "password": "secret-1",
    })
    assert saved.status_code == 200 and saved.json()["has_password"] is True
    # 响应永不回显明文密码
    assert "secret-1" not in saved.text

    # 测试发送：假邮件通道捕获收件人（连接层错误应如实回传 502——这里拦截在 provider 层）
    sent: list[tuple[str, str]] = []

    class Fake:
        channel = "smtp"
        def send(self, to, subject, text):
            sent.append((to, subject))

    monkeypatch.setattr(mail_factory, "get_mail_provider", lambda *a, **k: Fake())
    test = tc.post("/api/admin/settings/mail/test", json={"to": "owner@example.com"})
    assert test.status_code == 200 and sent == [("owner@example.com", "Agent Platform 测试邮件")]

    # 非法邮箱 → 400
    assert tc.post("/api/admin/settings/mail/test", json={"to": "not-an-email"}).status_code == 400

    # cloud 模式：非 admin 一律 403，admin 可见
    monkeypatch.setattr(settings, "auth_mode", "cloud")
    assert tc.get("/api/admin/settings/mail").status_code == 403
    current["id"] = ids["b"]
    other_user = db.get(User, ids["b"])
    other_user.is_admin = True
    db.commit()
    assert tc.get("/api/admin/settings/mail").status_code == 200


def test_search_endpoint_roundtrip(client) -> None:
    tc, _db, _ids, _current = client
    saved = tc.put("/api/admin/settings/search", json={"provider": "bing", "api_key": "bing-key"})
    assert saved.status_code == 200 and saved.json() == {"provider": "bing", "has_api_key": True}
    assert "bing-key" not in saved.text
    got = tc.get("/api/admin/settings/search")
    assert got.json() == {"provider": "bing", "has_api_key": True}
    # 未知搜索源 → 400
    assert tc.put("/api/admin/settings/search", json={"provider": "google"}).status_code == 400


def test_secret_store_smoke_still_works() -> None:
    """secret_store 基线不回归：local 加解密往返。"""
    enc = secret_store.encrypt("plain-secret")
    assert secret_store.decrypt(enc) == "plain-secret"
