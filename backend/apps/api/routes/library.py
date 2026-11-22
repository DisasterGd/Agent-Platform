"""资料库接口（v0.5）：查看/重命名/移动项目/删除/预览用户与 Agent 的文件。

约定与聊天接口一致：project_id 省略=全部，"none"=未归类，数字=指定项目；
PATCH 里显式传 null 才表示“移出项目”（未传字段不改动）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent_platform.infrastructure import filetypes as ft
from agent_platform.repositories.file_assets import UNSET
from agent_platform.services.library_service import LibraryService
from apps.api.dependencies import get_current_user_id, get_db

router = APIRouter(tags=["library"])

MAX_BATCH_DELETE = 200


class UpdateAssetIn(BaseModel):
    filename: str | None = None
    project_id: int | None = None  # 显式 null = 移出项目


class BatchDeleteIn(BaseModel):
    ids: list[int]
    keep_files: bool = False  # true=只从资料库移除记录，保留磁盘文件


def _project_filter(raw: str | None) -> Any:
    """省略=全部（UNSET）；"none"=未归类；数字=该项目。"""
    if raw is None:
        return UNSET
    if raw == "none":
        return None
    return int(raw)


@router.get("/library/assets")
def list_assets(
    project_id: str | None = None,
    kind: str | None = None,
    category: str | None = None,
    source: str | None = None,
    q: str | None = None,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    if kind and kind not in ft.KINDS:
        raise HTTPException(status_code=400, detail=f"未知类型：{kind}")
    return LibraryService(db).list(
        user_id,
        project_id=_project_filter(project_id),
        kind=kind,
        category=category,
        source=source,
        keyword=q,
        limit=limit,
        offset=offset,
    )


@router.post("/library/scan")
def scan_existing(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """把磁盘上已有、表里没有的历史文件登记进资料库（幂等，可重复调用）。"""
    registered = LibraryService(db).scan_existing(user_id)
    return {"registered": registered}


@router.get("/library/assets/{asset_id}")
def get_asset(
    asset_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    asset = LibraryService(db).get(asset_id, user_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    return asset


@router.get("/library/assets/{asset_id}/preview")
def preview_asset(
    asset_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """预览：text（含 content）/ image / audio / video / archive（含 entries）/ binary / missing。"""
    out = LibraryService(db).preview(asset_id, user_id)
    if out is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    return out


@router.patch("/library/assets/{asset_id}")
def update_asset(
    asset_id: int,
    body: UpdateAssetIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """重命名与项目归属可以一次提交；只处理请求里显式出现的字段。"""
    service = LibraryService(db)
    result = None
    try:
        if "project_id" in body.model_fields_set:
            result = service.move_project(asset_id, user_id, body.project_id)
        if body.filename is not None and body.filename.strip():
            result = service.rename(asset_id, user_id, body.filename) or result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    return result


@router.delete("/library/assets/{asset_id}", status_code=204)
def delete_asset(
    asset_id: int,
    keep_file: bool = Query(False, description="true=只删记录，保留磁盘文件"),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if not LibraryService(db).delete(asset_id, user_id, remove_file=not keep_file):
        raise HTTPException(status_code=404, detail="文件不存在")


@router.post("/library/assets/batch-delete")
def batch_delete(
    body: BatchDeleteIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    ids = [int(i) for i in body.ids[:MAX_BATCH_DELETE]]
    deleted = LibraryService(db).bulk_delete(ids, user_id, remove_file=not body.keep_files)
    return {"deleted": deleted}
