"""个人设置数据读写（v0.7）：user_settings 表的唯一访问入口（cloud 模式的 SettingsStore 后端）。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import UserSetting


class UserSettingsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def read(self, user_id: int) -> dict:
        """该用户的设置 JSON；从未保存过 → 空 dict（由 SettingsService 按 .env 兜底派生）。"""
        row = self.db.get(UserSetting, user_id)
        if row is None or not isinstance(row.data, dict):
            return {}
        return row.data

    def write(self, user_id: int, data: dict) -> None:
        row = self.db.get(UserSetting, user_id)
        if row is None:
            row = UserSetting(user_id=user_id, data=data)
            self.db.add(row)
        else:
            row.data = data
        self.db.commit()
