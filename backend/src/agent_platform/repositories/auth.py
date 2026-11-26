"""认证数据读写（v0.7）：sessions 与 auth_codes 的唯一访问入口。"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from agent_platform.config import settings
from agent_platform.infrastructure.database.models import AuthCode, UserSession


class SessionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, user_id: int, token_hash: str) -> UserSession:
        expires = datetime.now() + timedelta(days=settings.session_ttl_days)
        row = UserSession(user_id=user_id, token_hash=token_hash, expires_at=expires)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        stmt = select(UserSession).where(UserSession.token_hash == token_hash)
        return self.db.scalars(stmt).first()

    def touch(self, row: UserSession) -> None:
        """滑动续期：last_seen_at 每次都更新；过期临近（剩余 < 半个 TTL）才顺延 expires_at，
        避免每个请求都写 expires_at。"""
        now = datetime.now()
        row.last_seen_at = now
        half = timedelta(days=settings.session_ttl_days) / 2
        if row.expires_at - now < half:
            row.expires_at = now + timedelta(days=settings.session_ttl_days)
        self.db.commit()

    def revoke(self, token_hash: str) -> bool:
        row = self.get_by_token_hash(token_hash)
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = datetime.now()
        self.db.commit()
        return True

    def revoke_all_for_user(self, user_id: int) -> int:
        """撤销该用户全部未撤销会话（停用账号/踢下线用）。返回撤销数量。"""
        now = datetime.now()
        rows = list(self.db.scalars(
            select(UserSession).where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
            )
        ))
        for row in rows:
            row.revoked_at = now
        if rows:
            self.db.commit()
        return len(rows)

    def purge_expired(self) -> int:
        """清理已过期/已撤销超过保留期的会话行（启动时顺带执行）。"""
        cutoff = datetime.now() - timedelta(days=settings.session_ttl_days)
        stmt = delete(UserSession).where(
            (UserSession.expires_at < cutoff) | (UserSession.revoked_at < cutoff)
        )
        result = self.db.execute(stmt)
        self.db.commit()
        return int(result.rowcount or 0)


class AuthCodeRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, *, email: str, code_hash: str, purpose: str, expires_at: datetime, ip: str) -> AuthCode:
        row = AuthCode(
            email=email, code_hash=code_hash, purpose=purpose,
            expires_at=expires_at, created_ip=ip[:64],
            created_at=datetime.now(),  # 频控按 Python 本地时间算窗口：显式写入，避免 SQLite now()=UTC 的时区偏差
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def latest_active(self, email: str, purpose: str) -> AuthCode | None:
        """该邮箱最近一条未消费的验证码（旧未消费行会被新请求的频控挡住，不存在多行竞争）。"""
        stmt = (
            select(AuthCode)
            .where(AuthCode.email == email, AuthCode.purpose == purpose, AuthCode.consumed_at.is_(None))
            .order_by(AuthCode.id.desc())
            .limit(1)
        )
        return self.db.scalars(stmt).first()

    def count_since(self, email: str | None, since: datetime, ip: str | None = None) -> int:
        """频控计数：按邮箱或按 IP 统计时间窗内的发码次数。"""
        stmt = select(func.count(AuthCode.id)).where(AuthCode.created_at >= since)
        if email is not None:
            stmt = stmt.where(AuthCode.email == email)
        if ip is not None:
            stmt = stmt.where(AuthCode.created_ip == ip)
        return int(self.db.execute(stmt).scalar_one())

    def save_attempts(self, row: AuthCode) -> None:
        self.db.commit()

    def consume(self, row: AuthCode) -> None:
        row.consumed_at = datetime.now()
        self.db.commit()

    def purge_expired(self) -> int:
        """清理过期验证码行（启动时顺带执行）。"""
        stmt = delete(AuthCode).where(AuthCode.expires_at < datetime.now() - timedelta(hours=1))
        result = self.db.execute(stmt)
        self.db.commit()
        return int(result.rowcount or 0)
