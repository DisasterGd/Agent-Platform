"""设置接口（v0.7 起按当前用户读写）：读取/保存按供应商隔离的模型配置，探测可用模型。

安全约定：任何响应都不回显 API Key 明文，只回 has_api_key 布尔；
保存时 api_key 字段缺省=保留、空串=清除、非空=替换。
local 模式仍读写共享的 settings.json（行为同 v0.6）；cloud 模式读写 user_settings 表——
每个用户各配各的角色与 Key，互不可见（BYOK）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent_platform.infrastructure.model_discovery import (
    DiscoveryError,
    discover_models,
)
from agent_platform.services.settings_service import PRESETS, user_settings_service
from apps.api.dependencies import get_current_user_id, get_db

router = APIRouter(tags=["settings"])


class SettingsIn(BaseModel):
    """PUT 载荷：provider+base_url+api_key 写凭据档案；roles 写角色（出现哪个键替换哪个）。

    api_key 语义见模块 docstring；roles 值形如 {"provider":"qwen","model":"qwen3.8-omni-flash"} 或 null。
    """

    provider: str = ""
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    vision_model: str | None = None
    roles: dict | None = None
    memory_enabled: bool | None = None  # v0.4 自动记忆开关（None=保持当前值）


class DiscoverIn(BaseModel):
    """“获取可用模型”：Key 留空则回退到**正在编辑的供应商**已存的 Key（v0.7.1 起 provider 精确回退，
    不再用激活档案——否则会把 A 家的 Key 发给 B 家，必 401）；Key 只在内存中转发给 Base URL，不落盘不记录。"""

    base_url: str = ""
    api_key: str = ""
    provider: str = ""  # 正在编辑的供应商 id（如 qwen/zhipu）：回退凭据时精确取该家的 Key


def _view(user_id: int, db: Session) -> dict:
    service = user_settings_service(db, user_id)
    return {
        "config": service.public_config(),
        "profiles": service.profiles_view(),
        "roles": service.roles_view(),
        "presets": PRESETS,
    }


@router.get("/settings")
def get_settings(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    return _view(user_id, db)


@router.put("/settings")
def update_settings(
    body: SettingsIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    user_settings_service(db, user_id).save(body.model_dump())
    return _view(user_id, db)


@router.post("/settings/discover-models")
async def post_discover_models(
    body: DiscoverIn,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    base_url = body.base_url.strip()
    api_key = body.api_key.strip()
    if not base_url or not api_key:
        service = user_settings_service(db, user_id)
        provider = body.provider.strip()
        if provider:
            # 精确回退：编辑哪一家就用哪一家已存的 Key（绝不串别家的）
            saved_base_url, saved_api_key = service.resolve_provider_credentials(provider)
            base_url = base_url or saved_base_url
            api_key = api_key or saved_api_key
        else:
            cfg = service.load()  # 兼容不带 provider 的旧调用：回退激活档案
            base_url = base_url or str(cfg.get("base_url") or "")
            api_key = api_key or str(cfg.get("api_key") or "")
    try:
        models = await discover_models(base_url, api_key)
    except DiscoveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"models": models}
