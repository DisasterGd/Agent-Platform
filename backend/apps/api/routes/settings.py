"""设置接口：读取/保存用户模型配置，探测 OpenAI 兼容接口的可用模型。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent_platform.infrastructure.model_discovery import (
    DiscoveryError,
    discover_models,
)
from agent_platform.services.settings_service import PRESETS, get_settings_service

router = APIRouter(tags=["settings"])


class SettingsIn(BaseModel):
    provider: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    vision_model: str = ""
    memory_enabled: bool | None = None  # v0.4 自动记忆开关（None=保持当前值）


class DiscoverIn(BaseModel):
    """“获取可用模型”：只探用户自己填的 Base URL，凭据不落库不记录。"""

    base_url: str = ""
    api_key: str = ""


@router.get("/settings")
def get_settings() -> dict:
    return {"config": get_settings_service().load(), "presets": PRESETS}


@router.put("/settings")
def update_settings(body: SettingsIn) -> dict:
    config = get_settings_service().save(body.model_dump())
    return {"config": config, "presets": PRESETS}


@router.post("/settings/discover-models")
async def post_discover_models(body: DiscoverIn) -> dict:
    try:
        models = await discover_models(body.base_url, body.api_key)
    except DiscoveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"models": models}
