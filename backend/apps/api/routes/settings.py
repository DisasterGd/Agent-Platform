"""设置接口：读取/保存按供应商隔离的模型配置，探测 OpenAI 兼容接口的可用模型。

安全约定：任何响应都不回显 API Key 明文，只回 has_api_key 布尔；
保存时 api_key 字段缺省=保留、空串=清除、非空=替换。
"""
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
    """PUT 载荷：provider 指定写入哪个供应商档案；api_key 语义见模块 docstring。"""

    provider: str = ""
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    vision_model: str | None = None
    memory_enabled: bool | None = None  # v0.4 自动记忆开关（None=保持当前值）


class DiscoverIn(BaseModel):
    """“获取可用模型”：字段留空则回退到当前生效配置；Key 只在内存中转发给 Base URL，不落盘不记录。"""

    base_url: str = ""
    api_key: str = ""


def _view() -> dict:
    service = get_settings_service()
    return {"config": service.public_config(), "profiles": service.profiles_view(), "presets": PRESETS}


@router.get("/settings")
def get_settings() -> dict:
    return _view()


@router.put("/settings")
def update_settings(body: SettingsIn) -> dict:
    get_settings_service().save(body.model_dump())
    return _view()


@router.post("/settings/discover-models")
async def post_discover_models(body: DiscoverIn) -> dict:
    base_url = body.base_url.strip()
    api_key = body.api_key.strip()
    if not base_url or not api_key:
        cfg = get_settings_service().load()  # 明文只在内存流转到探测函数
        base_url = base_url or str(cfg.get("base_url") or "")
        api_key = api_key or str(cfg.get("api_key") or "")
    try:
        models = await discover_models(base_url, api_key)
    except DiscoveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"models": models}
