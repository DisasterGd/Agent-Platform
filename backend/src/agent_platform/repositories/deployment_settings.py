"""部署级配置数据读写（v0.8.0）。每 name 一行 JSON（邮件通道/搜索源等全站唯一配置）。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import DeploymentSetting


class DeploymentSettingsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, name: str) -> dict | None:
        row = self.db.get(DeploymentSetting, name)
        return dict(row.data) if row is not None else None

    def set(self, name: str, data: dict) -> dict:
        row = self.db.get(DeploymentSetting, name)
        if row is None:
            row = DeploymentSetting(name=name, data=data)
            self.db.add(row)
        else:
            row.data = data
        self.db.commit()
        self.db.refresh(row)
        return dict(row.data)
