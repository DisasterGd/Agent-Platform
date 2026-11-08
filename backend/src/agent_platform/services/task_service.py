"""任务业务用例（v0.3 实现）。"""
from __future__ import annotations

from sqlalchemy.orm import Session


class TaskService:
    def __init__(self, db: Session) -> None:
        self.db = db
