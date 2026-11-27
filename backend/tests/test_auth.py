"""v0.7 账号体系测试：验证码发码/验码/注册登录合一/频控 + 会话签发/续期/撤销/停用踢下线。

离线：sqlite 内存库；邮件用假 Provider 记录调用（真实验证码从假 Provider 捕获的正文里提取）。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent_platform.config import settings
from agent_platform.infrastructure.database.base import Base
from agent_platform.infrastructure.database.models import AuthCode, User, UserSession
from agent_platform.infrastructure.mail import factory as mail_factory
from agent_platform.services import auth_service
from agent_platform.services.auth_service import AuthError


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture()
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """假邮件通道：记录 send 调用（验证码测试从正文提取）。"""
    sent: list[dict] = []

    class FakeProvider:
        def send(self, to: str, subject: str, text: str) -> None:
            sent.append({"to": to, "subject": subject, "text": text})

    monkeypatch.setattr(mail_factory, "get_mail_provider", lambda *a, **k: FakeProvider())
    return sent


def _request(db: Session, email: str, outbox: list[dict], monkeypatch=None, ip: str = "10.0.0.1") -> str:
    auth_service.request_code(db, email, ip=ip)
    body = outbox[-1]["text"]
    match = re.search(r"\b(\d{6})\b", body)
    assert match, "邮件正文应包含 6 位验证码"
    return match.group(1)


def _verify(db: Session, email: str, code: str) -> tuple[User, str]:
    return auth_service.verify_code(db, email, code)


# ---------- 发码 ----------


def test_request_code_sends_hashed_code(db: Session, outbox: list[dict]) -> None:
    code = _request(db, "  Alice@Example.COM ", outbox)
    assert outbox[-1]["to"] == "alice@example.com"  # 归一化：小写去空格
    row = db.query(AuthCode).order_by(AuthCode.id.desc()).first()
    assert row is not None and row.email == "alice@example.com"
    assert row.code_hash != code and len(row.code_hash) == 64  # 只存哈希
    assert row.consumed_at is None and row.attempts == 0
    assert row.expires_at - datetime.now() <= timedelta(seconds=600)


def test_request_code_rate_limits(db: Session, outbox: list[dict]) -> None:
    email = "spam@example.com"
    _request(db, email, outbox)
    with pytest.raises(AuthError, match="频繁"):
        _request(db, email, outbox)  # 1 次/分钟
    # 换邮箱绕开邮箱频控，撞 IP 天配额（20 次/天）
    for i in range(20):
        auth_service.request_code(db, f"u{i}@example.com", ip="9.9.9.9")
    with pytest.raises(AuthError, match="频繁"):
        auth_service.request_code(db, "last@example.com", ip="9.9.9.9")


def _relax_per_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    """同邮箱连续取码的用例放宽 1 次/分钟频控（只测注册/停用流程本身）。"""
    monkeypatch.setattr(auth_service, "RATE_PER_MINUTE", (99, 60))


def test_request_code_rejects_bad_email(db: Session, outbox: list[dict]) -> None:
    with pytest.raises(AuthError, match="邮箱格式"):
        auth_service.request_code(db, "not-an-email", ip="")


# ---------- 验证 + 注册登录合一 ----------


def test_verify_creates_account_and_session(db: Session, outbox: list[dict]) -> None:
    email = "newbie@example.com"
    code = _request(db, email, outbox)
    user, token = _verify(db, email, code)
    assert user.email == email
    assert user.display_name == "newbie"  # 邮箱 @ 前段
    assert user.is_admin is False
    row = db.query(UserSession).filter(UserSession.user_id == user.id).first()
    assert row is not None and row.token_hash != token and len(row.token_hash) == 64
    assert row.expires_at > datetime.now()
    assert user.last_login_at is not None
    # 验证码已消费：同码重放失败
    with pytest.raises(AuthError, match="不存在"):
        _verify(db, email, code)


def test_verify_wrong_code_counts_attempts_then_dies(db: Session, outbox: list[dict]) -> None:
    email = "wrong@example.com"
    code = _request(db, email, outbox)
    for i in range(5):
        with pytest.raises(AuthError, match="错误"):
            _verify(db, email, "000000")
    with pytest.raises(AuthError, match="次数过多"):
        _verify(db, email, code)  # 正确的码也救不回来（已作废）
    row = db.query(AuthCode).order_by(AuthCode.id.desc()).first()
    assert row.attempts >= 5


def test_verify_wrong_code_does_not_consume(db: Session, outbox: list[dict]) -> None:
    email = "retry@example.com"
    code = _request(db, email, outbox)
    with pytest.raises(AuthError):
        _verify(db, email, "111111")
    user, token = _verify(db, email, code)  # 错一次后正确的码仍可用
    assert user.email == email


def test_verify_expired_code_rejected(db: Session, outbox: list[dict]) -> None:
    email = "late@example.com"
    code = _request(db, email, outbox)
    row = db.query(AuthCode).order_by(AuthCode.id.desc()).first()
    row.expires_at = datetime.now() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(AuthError, match="过期"):
        _verify(db, email, code)


def test_verify_login_register_unified(db: Session, outbox: list[dict], monkeypatch: pytest.MonkeyPatch) -> None:
    """登录注册合一：同一邮箱验证码即凭证；新邮箱验证通过直接建号，无需其它任何信息。"""
    _relax_per_minute(monkeypatch)
    email = "unified@example.com"
    code = _request(db, email, outbox)
    user, _ = _verify(db, email, code)
    code2 = _request(db, email, outbox)
    user2, _ = _verify(db, email, code2)
    assert user2.id == user.id  # 第二次验证 = 登录老账号
    code3 = _request(db, "another@example.com", outbox)
    user3, _ = _verify(db, "another@example.com", code3)
    assert user3.email == "another@example.com"  # 新邮箱 = 注册新号


def test_admin_email_becomes_admin(db: Session, outbox: list[dict], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "admin_email", "boss@example.com")
    code = _request(db, "BOSS@example.com", outbox)  # 大小写不敏感
    user, _ = _verify(db, "boss@example.com", code)
    assert user.is_admin is True


def test_disabled_user_cannot_login(
    db: Session, outbox: list[dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    _relax_per_minute(monkeypatch)
    email = "banned@example.com"
    code = _request(db, email, outbox)
    user, _ = _verify(db, email, code)
    user.status = "disabled"
    db.commit()
    code2 = _request(db, email, outbox)
    with pytest.raises(AuthError, match="停用"):
        _verify(db, email, code2)


# ---------- 会话 ----------


def test_resolve_session_renews_and_revokes(db: Session, outbox: list[dict]) -> None:
    email = "slider@example.com"
    code = _request(db, email, outbox)
    user, token = _verify(db, email, code)
    resolved = auth_service.resolve_session(db, token)
    assert resolved is not None and resolved.id == user.id
    # 滑动续期：过期临近时顺延
    row = db.query(UserSession).filter(UserSession.user_id == user.id).first()
    row.expires_at = datetime.now() + timedelta(days=1)  # 剩余 < 半个 TTL → touch 应顺延
    db.commit()
    auth_service.resolve_session(db, token)
    db.refresh(row)
    assert row.expires_at > datetime.now() + timedelta(days=5)
    # 撤销 → 立即失效
    auth_service.revoke_session(db, token)
    assert auth_service.resolve_session(db, token) is None


def test_disabled_user_kicked_by_revoke_all(db: Session, outbox: list[dict]) -> None:
    email = "kick@example.com"
    code = _request(db, email, outbox)
    user, token = _verify(db, email, code)
    assert auth_service.resolve_session(db, token) is not None
    auth_service.revoke_all_sessions(db, user.id)
    assert auth_service.resolve_session(db, token) is None
    # 停用状态也不认
    user.status = "disabled"
    db.commit()
    assert auth_service.resolve_session(db, token) is None


def test_resolve_rejects_garbage(db: Session) -> None:
    assert auth_service.resolve_session(db, "") is None
    assert auth_service.resolve_session(db, "forged-token") is None


def test_purge_expired_rows(db: Session, outbox: list[dict]) -> None:
    email = "purge@example.com"
    code = _request(db, email, outbox)
    user, token = _verify(db, email, code)
    row = db.query(UserSession).filter(UserSession.user_id == user.id).first()
    code_row = db.query(AuthCode).order_by(AuthCode.id.desc()).first()
    row.expires_at = datetime.now() - timedelta(days=60)
    code_row.expires_at = datetime.now() - timedelta(hours=2)
    db.commit()
    auth_service.purge_expired(db)
    assert db.query(UserSession).count() == 0
    assert db.query(AuthCode).count() == 0


# ---------- secret_store：cloud=Fernet / local=DPAPI，按前缀互认 ----------


def test_secret_store_fernet_backend_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_platform.infrastructure import secret_store

    monkeypatch.setattr(settings, "auth_mode", "cloud")
    monkeypatch.setattr(settings, "service_secret", "a-service-secret")
    stored = secret_store.encrypt("sk-cloud-key")
    assert stored.startswith("enc:f1:") and "sk-cloud-key" not in stored
    assert secret_store.decrypt(stored) == "sk-cloud-key"
    # 换密钥（换 SERVICE_SECRET）→ 解不开，按未配置处理（绝不解出错误内容）
    monkeypatch.setattr(settings, "service_secret", "another-secret")
    assert secret_store.decrypt(stored) == ""
    # 历史 DPAPI 前缀与无前缀明文原样透传
    assert secret_store.decrypt("enc:v1:legacy-from-windows") is not None  # 解不开返回空，不抛
    assert secret_store.decrypt("plain-legacy-key") == "plain-legacy-key"


def test_secret_store_cloud_requires_service_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_platform.infrastructure import secret_store

    monkeypatch.setattr(settings, "auth_mode", "cloud")
    monkeypatch.setattr(settings, "service_secret", "")
    with pytest.raises(RuntimeError, match="SERVICE_SECRET"):
        secret_store.encrypt("sk-no-secret")  # 宁可失败也绝不把明文 Key 落盘


def test_migrate_root_files_to_user_dirs_is_idempotent(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_platform.infrastructure.storage import local as local_storage
    from agent_platform.infrastructure.storage.local import LocalStorage
    from agent_platform.infrastructure.storage.migrate import migrate_root_files_to_user_dirs

    store = LocalStorage(tmp_path)
    monkeypatch.setattr(local_storage, "_storage", store)
    (store.uploads / "老报告.md").write_bytes(b"# old")
    (store.generated / "旧产物.pdf").write_bytes(b"%PDF")

    moved = migrate_root_files_to_user_dirs(1)
    assert moved == 2
    assert store.resolve("uploads", "老报告.md", 1) is not None
    assert store.resolve("generated", "旧产物.pdf", 1) is not None
    assert (store.uploads / "老报告.md").exists() is False
    # 幂等：第二次没有可搬的了；同名已存在时不覆盖
    assert migrate_root_files_to_user_dirs(1) == 0
    (store.uploads / "同名.md").write_bytes(b"root")
    (store.user_dir("uploads", 2)).mkdir(parents=True, exist_ok=True)
    (store.user_dir("uploads", 2) / "同名.md").write_bytes(b"user2")
    assert migrate_root_files_to_user_dirs(2) == 0  # 目标已存在 → 跳过
    assert (store.user_dir("uploads", 2) / "同名.md").read_bytes() == b"user2"
    assert (store.uploads / "同名.md").read_bytes() == b"root"


def test_local_mode_first_login_binds_dev_account(
    db: Session, outbox: list[dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    """v0.7.2 本地模式登录语义：首次登录绑定本地默认账号（数据保留、可随时登录取回），之后的邮箱建新号。"""
    from agent_platform.repositories.users import UserRepository

    monkeypatch.setattr(settings, "auth_mode", "local")
    _relax_per_minute(monkeypatch)
    UserRepository(db).ensure_user(settings.dev_user_id, "developer")

    code = _request(db, "owner@example.com", outbox)
    user, token = _verify(db, "owner@example.com", code)
    assert user.id == settings.dev_user_id          # 绑定到本地默认账号，不是建新号
    assert user.email == "owner@example.com"
    assert user.display_name == "owner"

    code2 = _request(db, "owner@example.com", outbox)
    user2, _ = _verify(db, "owner@example.com", code2)
    assert user2.id == settings.dev_user_id          # 已绑定邮箱：登录即取回该账号

    code3 = _request(db, "second@example.com", outbox)
    user3, _ = _verify(db, "second@example.com", code3)
    assert user3.id != settings.dev_user_id          # 新邮箱 → 新账号（本机多账号）
    assert user3.email == "second@example.com"
    # 默认账号的数据不受影响
    assert UserRepository(db).get(settings.dev_user_id).email == "owner@example.com"


def test_local_mode_cloud_already_bound_creates_normally(
    db: Session, outbox: list[dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    """cloud 模式没有"绑定默认账号"逻辑：任何新邮箱都是新号（隔离语义不变）。"""
    monkeypatch.setattr(settings, "auth_mode", "cloud")
    from agent_platform.repositories.users import UserRepository

    UserRepository(db).ensure_user(settings.dev_user_id, "developer")  # 即使存在无邮箱的默认账号
    code = _request(db, "fresh@example.com", outbox)
    user, _ = _verify(db, "fresh@example.com", code)
    assert user.id != settings.dev_user_id
    assert user.email == "fresh@example.com"
