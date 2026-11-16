"""设置接口：读取/保存用户模型配置。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from agent_platform.services.settings_service import PRESETS, get_settings_service

router = APIRouter(tags=["settings"])


class SettingsIn(BaseModel):
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    vision_model: str = ""


@router.get("/settings")
def get_settings() -> dict:
    return {"config": get_settings_service().load(), "presets": PRESETS}


@router.put("/settings")
def update_settings(body: SettingsIn) -> dict:
    config = get_settings_service().save(body.model_dump())
    return {"config": config, "presets": PRESETS}
