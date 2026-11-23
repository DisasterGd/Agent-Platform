"""根据配置创建模型适配器。

模型配置优先级：用户设置（data/settings.json）> .env。前端设置页可改。
新增模型（含未来多模态）时调用 register_model_provider 登记 builder；默认走 OpenAI 兼容接口。
"""
from __future__ import annotations

from collections.abc import Callable

from agent_platform.config import settings
from agent_platform.models.base import ChatModel
from agent_platform.models.openai_compatible import OpenAICompatibleModel
from agent_platform.services.settings_service import get_settings_service

# name -> builder() -> ChatModel | None
_providers: dict[str, Callable[[], ChatModel | None]] = {}


def register_model_provider(name: str, builder: Callable[[], ChatModel | None]) -> None:
    """登记一个模型供应商，供后续多模态/多模型切换使用。"""
    _providers[name] = builder


def _active_config() -> dict:
    return get_settings_service().load()  # 兜底链（profile > .env > 预设）已在服务层做完


def _build_openai_compatible() -> ChatModel | None:
    cfg = _active_config()
    if not cfg.get("api_key"):
        return None
    return OpenAICompatibleModel(
        base_url=cfg.get("base_url") or "",
        api_key=cfg["api_key"],
        model=cfg.get("model") or "",
        temperature=settings.llm_temperature,
    )


# 默认供应商：DeepSeek（OpenAI 兼容接口）。多模态模型可在其 provider 内部
# 读取相应配置，并返回实现了 ChatModel 协议（含 images）的实例。
register_model_provider("deepseek", _build_openai_compatible)
register_model_provider("openai_compatible", _build_openai_compatible)


def create_model(provider: str | None = None) -> ChatModel | None:
    """未配置 API Key 时返回 None，由调用方回退到演示模式。"""
    name = provider or settings.llm_provider
    builder = _providers.get(name) or _providers.get("openai_compatible")
    if builder is None:
        return None
    return builder()


def create_vision_model() -> ChatModel | None:
    """视觉模型（用于识图）：与主模型同档案（同 Base URL/Key），仅模型名不同。未配置时返回 None。"""
    cfg = _active_config()
    vision_model = (cfg.get("vision_model") or "").strip()
    if not vision_model or not cfg.get("api_key"):
        return None
    return OpenAICompatibleModel(
        base_url=cfg.get("base_url") or "",
        api_key=cfg["api_key"],
        model=vision_model,
        temperature=0.0,
    )


def list_model_providers() -> list[str]:
    return sorted(_providers.keys())
