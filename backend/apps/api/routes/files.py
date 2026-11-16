"""文件上传与下载接口（v0.2）。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from agent_platform.infrastructure.storage.local import get_storage

router = APIRouter(tags=["files"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB


@router.post("/files", status_code=201)
async def upload_file(file: Annotated[UploadFile, File()]) -> dict:
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件过大，最大支持 20MB")
    stored = get_storage().save(
        category="uploads",
        filename=file.filename or "file",
        content=content,
        content_type=file.content_type or "application/octet-stream",
    )
    return stored.to_dict()


@router.get("/files/{category}/{name}")
def download_file(category: str, name: str) -> FileResponse:
    storage = get_storage()
    if category not in ("uploads", "generated"):
        raise HTTPException(status_code=404, detail="文件不存在")
    path = storage.resolve(category, name)
    if path is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=path.name)
