"""任务接口占位（v0.3 实现）。"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["tasks"])


@router.get("/tasks")
def list_tasks() -> list:
    return []
