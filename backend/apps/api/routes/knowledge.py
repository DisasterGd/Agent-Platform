"""知识库接口（v0.6.1，v0.5 收尾）：切块检索与重建索引。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from agent_platform.services.knowledge_service import KnowledgeService
from apps.api.dependencies import get_current_user_id, get_db

router = APIRouter(tags=["knowledge"])


@router.get("/knowledge/search")
def search_knowledge(
    q: str = Query(..., min_length=1, max_length=200, description="检索关键词"),
    project_id: int | None = Query(None, description="限定项目（省略=全库）"),
    limit: int = Query(8, ge=1, le=24),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    result = KnowledgeService(db).search(user_id, q.strip(), project_id=project_id, limit=limit)
    if not result["terms"]:
        raise HTTPException(status_code=400, detail="检索词无效：请至少包含一个字母、数字或汉字")
    return result


@router.post("/knowledge/reindex")
def reindex(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """给还没切块的上传文件补索引（已切过的不重切）；失败文件计入 scanned 而不计入 indexed。"""
    return KnowledgeService(db).reindex_missing(user_id)
