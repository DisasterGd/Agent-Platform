"""项目接口（v0.4）：左侧项目栏的增删改查与置顶。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from agent_platform.services.project_service import ProjectService
from apps.api.dependencies import get_current_user_id, get_db

router = APIRouter(tags=["projects"])


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    name: str
    description: str
    pinned: bool
    created_at: datetime
    updated_at: datetime


class CreateProjectIn(BaseModel):
    name: str
    description: str = ""


class UpdateProjectIn(BaseModel):
    name: str | None = None
    description: str | None = None
    pinned: bool | None = None


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return ProjectService(db).list(user_id)


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(
    body: CreateProjectIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    return ProjectService(db).create(user_id, body.name, body.description)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    body: UpdateProjectIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    project = ProjectService(db).update(project_id, user_id, body.name, body.description, body.pinned)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if not ProjectService(db).delete(project_id, user_id):
        raise HTTPException(status_code=404, detail="项目不存在")
