"""用户数据读写（v0.7）：users 表的唯一访问入口。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import User


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        return self.db.scalars(stmt).first()

    def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        return self.db.scalars(stmt).first()

    def create(
        self, *, username: str, email: str | None = None, display_name: str = "",
        is_admin: bool = False,
    ) -> User:
        user = User(
            username=username[:80],
            email=email,
            display_name=(display_name or "")[:120],
            is_admin=is_admin,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def ensure_user(self, user_id: int, username: str) -> User:
        """确保指定 id 的用户存在（local 模式启动时补种 dev 用户，幂等）。"""
        existing = self.db.get(User, user_id)
        if existing is not None:
            return existing
        user = User(id=user_id, username=username[:80])
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def bind_email(self, user_id: int, email: str, display_name: str = "") -> User | None:
        """把邮箱绑定到既有账号（v0.7.2 本地模式"首次登录绑定默认账号"用）。

        绑定后该邮箱即可通过验证码登录此账号、取回它的全部已有数据；display_name 缺省时补邮箱前段。
        """
        user = self.db.get(User, user_id)
        if user is None:
            return None
        user.email = email
        if not user.display_name and display_name:
            user.display_name = display_name[:120]
        self.db.commit()
        self.db.refresh(user)
        return user

    def touch_login(self, user_id: int) -> None:
        """登录成功时刻（last_login_at，供 admin 列表展示）。"""
        user = self.db.get(User, user_id)
        if user is not None:
            user.last_login_at = datetime.now()
            self.db.commit()

    def set_status(self, user_id: int, status: str) -> User | None:
        user = self.db.get(User, user_id)
        if user is None:
            return None
        user.status = status
        self.db.commit()
        self.db.refresh(user)
        return user

    def set_display_name(self, user_id: int, display_name: str) -> User | None:
        user = self.db.get(User, user_id)
        if user is None:
            return None
        user.display_name = display_name.strip()[:120]
        self.db.commit()
        self.db.refresh(user)
        return user

    def search(
        self, keyword: str | None = None, *, limit: int = 50, offset: int = 0
    ) -> list[User]:
        """admin 用户列表：email/display_name/username 模糊搜索 + 分页。"""
        stmt = select(User).order_by(User.created_at.desc(), User.id.desc())
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(User.email.like(like), User.display_name.like(like), User.username.like(like))
            )
        stmt = stmt.limit(max(1, int(limit))).offset(max(0, int(offset)))
        return list(self.db.scalars(stmt))

    def count_all(self, keyword: str | None = None) -> int:
        stmt = select(func.count(User.id))
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(User.email.like(like), User.display_name.like(like), User.username.like(like))
            )
        return int(self.db.execute(stmt).scalar_one())

    def count_by_status(self) -> dict[str, int]:
        stmt = select(User.status, func.count(User.id)).group_by(User.status)
        return {str(k): int(c) for k, c in self.db.execute(stmt)}
