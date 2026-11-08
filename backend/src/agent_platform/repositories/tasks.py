"""任务数据读写（v0.3 实现）。"""
from __future__ import annotations

from sqlalchemy.orm import Session


class TaskRepository:
    def __init__(self, db: Session) -> None:
        self.db = db
