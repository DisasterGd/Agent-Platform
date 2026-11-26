"""按角色创建模型适配器（v0.6 角色化配置）。

roles.reasoning → 主模型（对话/任务/工具循环/记忆提炼）
roles.vision    → 视觉模型（识图：把附件图片描述为文本）
roles.image_gen → 生图配置（generate_image 工具消费，不在此建 ChatModel）

每个角色引用某个供应商档案的凭据（Base URL/Key），因此可以跨厂商组合——
推理用 DeepSeek、识图用百炼、生图用智谱，各用各的 Key。未配置 API Key 时一律返回 None，
由调用方回退到演示模式或提示未配置。

新增原生供应商时调用 register_model_provider(name, builder) 登记；默认走 OpenAI 兼容接口。
"""
from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from agent_platform.config import settings
from agent_platform.models.base import ChatModel
from agent_platform.models.openai_compatible import OpenAICompatibleModel
from agent_platform.services.settings_service import (
    SettingsService,
    get_settings_service,
    user_settings_service,
)

# name -> builder(cfg: dict, temperature: float) -> ChatModel
_providers: dict[str, Callable[[dict, float], ChatModel]] = {}


def register_model_provider(name: str, builder: Callable[[dict, float], ChatModel]) -> None:
    """登记一个供应商的适配器构造器（未来原生协议/多模态在此接入）。"""
    _providers[name] = builder


def _default_builder(cfg: dict, temperature: float) -> ChatModel:
    return OpenAICompatibleModel(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=temperature,
    )


register_model_provider("openai_compatible", _default_builder)


def _role_service(db: Session | None = None, user_id: int | None = None) -> SettingsService:
    """角色配置来源：cloud 模式按用户隔离（user_settings 表）；local/无参=共享文件单例。

    生产链路（chat/task/knowledge 服务）一律传 (db, user_id)；不传保留 v0.6 行为，
    供测试与本地脚本直接使用全局 settings.json。
    """
    if db is None and user_id is None:
        return get_settings_service()
    return user_settings_service(db, user_id)


def _build(role_cfg: dict | None, temperature: float) -> ChatModel | None:
    if not role_cfg or not role_cfg.get("api_key"):
        return None
    builder = _providers.get(role_cfg["provider"]) or _providers["openai_compatible"]
    return builder(role_cfg, temperature)


def create_model(db: Session | None = None, user_id: int | None = None,
                 provider: str | None = None) -> ChatModel | None:
    """主模型（推理角色）。provider 仅为兼容旧调用保留，实际由 roles.reasoning 决定。"""
    return _build(_role_service(db, user_id).resolve_role("reasoning"), settings.llm_temperature)


def create_vision_model(db: Session | None = None, user_id: int | None = None) -> ChatModel | None:
    """识图模型（视觉角色）。未配置或该供应商无 Key 时返回 None（附件图片将不被描述）。"""
    return _build(_role_service(db, user_id).resolve_role("vision"), 0.0)


def create_image_config(db: Session | None = None, user_id: int | None = None) -> dict | None:
    """生图角色配置 {base_url, api_key, model}；未配置返回 None（generate_image 工具据此提示）。"""
    cfg = _role_service(db, user_id).resolve_role("image_gen")
    if not cfg or not cfg.get("api_key"):
        return None
    return cfg


def list_model_providers() -> list[str]:
    return sorted(_providers.keys())
