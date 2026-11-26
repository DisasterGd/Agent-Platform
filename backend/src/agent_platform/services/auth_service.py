"""账号体系用例（v0.7）：邮箱验证码登录/注册合一 + 服务端会话。

流程（与 docs/design-v0.7-v0.8.md 3.3 一致）：
- request-code：频控检查 → 6 位数字码（secrets）→ 只存 SHA-256 哈希（10 分钟有效）→ MailProvider 发信；
  响应不区分邮箱是否存在（防枚举）。
- verify：哈希一致 + 未过期 + 未消费 + attempts<5 → 消费 → 无账号则建号（验证码即凭证，
  display_name 取邮箱 @ 前段）→ 签发 session（token_urlsafe，库存哈希）。
- 会话选服务端 session 表 + cookie，不选 JWT：可撤销（封号/踢设备即时生效）、不用管密钥轮换；
  30 天滑动续期。cookie 名固定 ap_session。

防滥用（auth_codes 计数即可，不引入限流依赖）：每邮箱 1 次/分钟、5 次/小时、10 次/天；每 IP 20 次/天。
注册邀请码：.env 配了 INVITE_CODE 时，新邮箱建号必须带对邀请码（登录老账号不受影响）。
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from agent_platform.config import settings
from agent_platform.infrastructure.database.models import User
from agent_platform.repositories.auth import AuthCodeRepository, SessionRepository
from agent_platform.repositories.users import UserRepository

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CODE_TTL_SECONDS = 600          # 验证码 10 分钟有效
CODE_MAX_ATTEMPTS = 5           # 错 5 次作废
SESSION_COOKIE = "ap_session"   # 决策点 #7：cookie 名固定

# 发码频控：每邮箱 1 次/分钟、5 次/小时、10 次/天；每 IP 20 次/天
RATE_PER_MINUTE = (1, 60)
RATE_PER_HOUR = (5, 3600)
RATE_PER_DAY = (10, 86400)
RATE_IP_PER_DAY = (20, 86400)


class AuthError(Exception):
    """带用户可读信息的认证失败（路由层转 400/429）。"""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def normalize_email(email: str) -> str:
    cleaned = (email or "").strip().lower()
    if not EMAIL_RE.match(cleaned) or len(cleaned) > 255:
        raise AuthError("邮箱格式不正确")
    return cleaned


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def request_code(db: Session, email: str, ip: str = "") -> None:
    """生成并发送登录/注册验证码。发送失败不在响应里体现（统一 204 防枚举），只记日志。"""
    import logging

    email = normalize_email(email)
    codes = AuthCodeRepository(db)
    now = datetime.now()

    def _rate(limit: int, window: int, *, by_ip: bool = False) -> None:
        count = codes.count_since(None if by_ip else email, now - timedelta(seconds=window),
                                  ip if by_ip else None)
        if count >= limit:
            raise AuthError("验证码发送太频繁，请稍后再试", status_code=429)

    _rate(*RATE_PER_MINUTE)
    _rate(*RATE_PER_HOUR)
    _rate(*RATE_PER_DAY)
    _rate(*RATE_IP_PER_DAY, by_ip=True)

    code = f"{secrets.randbelow(1_000_000):06d}"
    codes.create(
        email=email,
        code_hash=_hash_code(code),
        purpose="login",
        expires_at=now + timedelta(seconds=CODE_TTL_SECONDS),
        ip=ip,
    )

    from agent_platform.infrastructure.mail.factory import get_mail_provider

    provider = get_mail_provider()
    body = (
        "你的 Agent Platform 登录验证码：\n\n"
        f"{code}\n\n"
        f"{CODE_TTL_SECONDS // 60} 分钟内有效。若不是你本人操作，请忽略本邮件。"
    )
    try:
        provider.send(email, "Agent Platform 登录验证码", body)
    except Exception:  # noqa: BLE001 — 发送失败不向响应泄露邮箱存在性，只记日志便于排障
        logging.getLogger("agent_platform.auth").exception("验证码邮件发送失败（to=%s）", email)


def verify_code(db: Session, email: str, code: str, invite_code: str = "", ip: str = "") -> tuple[User, str]:
    """校验验证码并签发会话。返回 (user, 明文 token)；邮箱未注册且验证通过即注册（登录注册合一）。"""
    email = normalize_email(email)
    cleaned_code = (code or "").strip()
    if not cleaned_code:
        raise AuthError("请输入验证码")
    codes = AuthCodeRepository(db)
    row = codes.latest_active(email, "login")
    if row is None:
        raise AuthError("验证码不存在或已被使用，请重新获取")
    if row.expires_at < datetime.now():
        raise AuthError("验证码已过期，请重新获取")
    if row.attempts >= CODE_MAX_ATTEMPTS:
        raise AuthError("验证码错误次数过多，请重新获取")
    if row.code_hash != _hash_code(cleaned_code):
        row.attempts += 1
        codes.save_attempts(row)
        left = CODE_MAX_ATTEMPTS - row.attempts
        hint = f"验证码错误（还可尝试 {left} 次）" if left > 0 else "验证码错误次数过多，请重新获取"
        raise AuthError(hint)

    codes.consume(row)

    users = UserRepository(db)
    user = users.get_by_email(email)
    if user is None and settings.auth_mode == "local":
        # 本地模式首次登录：把邮箱绑定到本地默认账号（而非建新号）——
        # 已有的全部数据保留原归属，此后通过登录即可随时取回；绑定不需要邀请码。
        dev_user = users.get(settings.dev_user_id)
        if dev_user is not None and not dev_user.email:
            users.bind_email(dev_user.id, email, email.split("@", 1)[0])
            user = dev_user
    if user is None:
        # 注册环节：.env 配了邀请码则必须正确（决策点 #2）
        expected = (settings.invite_code or "").strip()
        if expected and (invite_code or "").strip() != expected:
            raise AuthError("邀请码错误：首次注册需要有效的邀请码")
        local_part = email.split("@", 1)[0][:80]
        username = email[:80]
        if users.get_by_username(username) is not None:
            username = f"{local_part[:70]}-{secrets.token_hex(4)}"  # 极少发生：撞名加短随机后缀
        user = users.create(
            username=username,
            email=email,
            display_name=local_part,
            is_admin=bool(settings.admin_email.strip().lower()) and email == settings.admin_email.strip().lower(),
        )

    if user.status != "active":
        raise AuthError("账号已被停用，请联系管理员")

    token = issue_session(db, user.id)
    users.touch_login(user.id)
    return user, token


def issue_session(db: Session, user_id: int) -> str:
    """签发会话：token 只进 cookie，库里只存 SHA-256。"""
    token = secrets.token_urlsafe(32)
    SessionRepository(db).create(user_id, hashlib.sha256(token.encode("utf-8")).hexdigest())
    return token


def resolve_session(db: Session, token: str) -> User | None:
    """cookie token → 当前用户。校验：会话未撤销/未过期 + 账号 active；命中即滑动续期。"""
    if not token:
        return None
    row = SessionRepository(db).get_by_token_hash(hashlib.sha256(token.encode("utf-8")).hexdigest())
    if row is None or row.revoked_at is not None or row.expires_at < datetime.now():
        return None
    user = UserRepository(db).get(row.user_id)
    if user is None or user.status != "active":
        return None
    SessionRepository(db).touch(row)
    return user


def revoke_session(db: Session, token: str) -> None:
    SessionRepository(db).revoke(hashlib.sha256(token.encode("utf-8")).hexdigest())


def revoke_all_sessions(db: Session, user_id: int) -> int:
    """撤销该用户全部会话（停用账号即踢下线）。"""
    return SessionRepository(db).revoke_all_for_user(user_id)


def purge_expired(db: Session) -> None:
    """启动时顺带清理过期会话与验证码行（表不会无限膨胀）。"""
    SessionRepository(db).purge_expired()
    AuthCodeRepository(db).purge_expired()
