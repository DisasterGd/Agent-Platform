"""文件上传与下载接口（v0.2 起；v0.5 起同时登记资料库）。

上传即登记为“未归类”条目，发送消息时由 ChatService 补写会话/项目归属；
下载走磁盘真实名，但显示名取资料库里的 filename，所以重命名后下载得到新名字。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from agent_platform.infrastructure.filetypes import content_type_for
from agent_platform.infrastructure.storage.local import get_storage
from agent_platform.services.knowledge_service import KnowledgeService
from agent_platform.services.library_service import LibraryService
from apps.api.dependencies import get_current_user_id, get_db

router = APIRouter(tags=["files"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB


@router.post("/files", status_code=201)
async def upload_file(
    file: Annotated[UploadFile, File()],
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件过大，最大支持 20MB")
    name = file.filename or "file"
    stored = get_storage().save(
        category="uploads",
        filename=name,
        content=content,
        content_type=file.content_type or content_type_for(name),
    )
    # 登记资料库：上传此刻还不知道会进哪个会话，归属在发送消息时补写
    asset = LibraryService(db).register_saved(stored, user_id=user_id, source="upload")
    # v0.6.1 知识库：上传即尝试切块（图片/二进制自然跳过；异常只吞断，绝不阻断上传）
    KnowledgeService(db).auto_index(int(asset["id"]))
    return {**stored.to_dict(), "asset_id": asset["id"], "kind_label": asset["kind_label"]}


@router.get("/files/{category}/{name}")
def download_file(
    category: str,
    name: str,
    inline: bool = Query(False, description="true=浏览器内预览（图像/音视频/文本），false=作为附件下载"),
    db: Session = Depends(get_db),
) -> FileResponse:
    storage = get_storage()
    if category not in ("uploads", "generated"):
        raise HTTPException(status_code=404, detail="文件不存在")
    path = storage.resolve(category, name)
    if path is None:
        raise HTTPException(status_code=404, detail="文件不存在")
    display = LibraryService(db).display_name(category, name) or name
    return FileResponse(
        path,
        filename=display,
        media_type=content_type_for(display),
        content_disposition_type="inline" if inline else "attachment",
    )
