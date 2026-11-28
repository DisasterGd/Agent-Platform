"""本地项目接口（v0.7.4）：真实目录注册与选目录浏览（伪编辑器 0.7.5、对话工具 0.7.6 接力）。

仅 local 模式可用：router 挂载在 main.py 里按 auth_mode 条件包含，路由层再挂 require_local_mode
双保险（防 import 时序差异）；cloud 模式下整组端点 404——远程用户没有"本地磁盘"可言。
身份铁律不变：user_id 只来自 get_current_user_id，归属校验在服务/仓库层。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from agent_platform.config import settings
from agent_platform.infrastructure.database.models import LocalProject
from agent_platform.repositories.local_projects import LocalProjectRepository
from agent_platform.services import local_project_service
from agent_platform.services.local_project_service import LocalProjectError
from apps.api.dependencies import get_current_user_id, get_db


def _require_local_mode() -> None:
    """cloud 模式下整组端点 404（与 main.py 的条件挂载双保险，防 import 时序差异）。"""
    if settings.auth_mode != "local":
        raise HTTPException(status_code=404, detail="Not Found")


router = APIRouter(tags=["local-projects"], dependencies=[Depends(_require_local_mode)])


def _get_owned(db: Session, user_id: int, project_id: int) -> LocalProject:
    """归属校验统一入口：非本人/不存在一律 404（不暴露存在性）。"""
    project = LocalProjectRepository(db).get_owned(project_id, user_id)
    if project is None:
        raise HTTPException(status_code=404, detail="本地项目不存在")
    return project


class LocalProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    root_path: str
    allow_write: bool
    created_at: datetime
    updated_at: datetime


class CreateLocalProjectIn(BaseModel):
    root_path: str
    title: str = ""


class UpdateLocalProjectIn(BaseModel):
    title: str | None = None
    allow_write: bool | None = None


@router.get("/local-projects", response_model=list[LocalProjectOut])
def list_local_projects(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return LocalProjectRepository(db).list_by_user(user_id)


@router.post("/local-projects", response_model=LocalProjectOut, status_code=201)
def create_local_project(
    body: CreateLocalProjectIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    repo = LocalProjectRepository(db)
    try:
        root = local_project_service.normalize_root(body.root_path)
    except LocalProjectError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    root_str = str(root)
    if repo.get_by_root(user_id, root_str) is not None:
        raise HTTPException(status_code=400, detail="该目录已注册为本地项目")
    title = body.title.strip() or root.name or "本地项目"
    return repo.create(user_id, title, root_str)


@router.patch("/local-projects/{project_id}", response_model=LocalProjectOut)
def update_local_project(
    project_id: int,
    body: UpdateLocalProjectIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    project = _get_owned(db, user_id, project_id)
    return LocalProjectRepository(db).update(project, title=body.title, allow_write=body.allow_write)


@router.delete("/local-projects/{project_id}", status_code=204)
def delete_local_project(
    project_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    project = _get_owned(db, user_id, project_id)
    LocalProjectRepository(db).delete(project)  # 只删注册行，磁盘文件不动


@router.get("/local-projects/{project_id}/tree")
def tree(
    project_id: int,
    path: str = ".",
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """伪编辑器目录树：单层懒加载（前端点开目录才取下一层），归属+路径安全双校验。"""
    project = _get_owned(db, user_id, project_id)
    try:
        return local_project_service.list_layer(Path(project.root_path), path)
    except LocalProjectError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/local-projects/{project_id}/file")
def file_content(
    project_id: int,
    path: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """伪编辑器文件内容：text/image/binary 三态（大小上限见 local_project_service）。"""
    project = _get_owned(db, user_id, project_id)
    try:
        return local_project_service.read_file(Path(project.root_path), path)
    except LocalProjectError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/local-projects/drives")
def drives(_auth: int = Depends(get_current_user_id)) -> dict:
    return {"drives": local_project_service.list_drives()}


@router.get("/local-projects/browse")
def browse(
    path: str,
    _auth: int = Depends(get_current_user_id),
) -> dict:
    try:
        return local_project_service.browse(path)
    except LocalProjectError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/local-projects/pick")
async def pick_directory(_auth: int = Depends(get_current_user_id)) -> dict:
    """弹系统原生目录选择对话框（v0.8.2，Windows 文件管理器外观），返回选中路径；取消返回 null。

    阻塞调用放线程池跑（对话框等用户操作，可能很久），不占用事件循环；
    同一时刻只允许一个对话框（并发第二请求 409）。只返回路径、不触碰文件系统——
    真正的注册仍走 POST /local-projects（normalize_root 白名单校验不变）。
    """
    import asyncio

    try:
        path = await asyncio.to_thread(local_project_service.pick_directory)
    except LocalProjectError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"path": path}
