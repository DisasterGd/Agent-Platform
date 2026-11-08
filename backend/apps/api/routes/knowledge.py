"""知识库接口占位（v0.5 实现）。"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["knowledge"])


@router.get("/knowledge/documents")
def list_documents() -> list:
    return []
