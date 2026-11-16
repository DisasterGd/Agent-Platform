"""根据配置创建模型适配器，并提供可扩展的供应商登记表。

新增模型（含未来多模态模型）时，调用 register_model_provider 登记一个
builder 即可，无需改动 Agent 核心。默认登记 OpenAI 兼容接口（DeepSeek）。
"""
from __future__ import annotations

from collections.abc import Callable

from agent_platform.config import settings
from agent_platform.models.base import ChatModel
from agent_platform.models.openai_compatible import OpenAICompatibleModel

# name -> builder() -> ChatModel | None
_providers: dict[str, Callable[[], ChatModel | None]] = {}


def register_model_provider(name: str, builder: Callable[[], ChatModel | None]) -> None:
    """登记一个模型供应商，供后续多模态/多模型切换使用。"""
    _providers[name] = builder


def _build_openai_compatible() -> ChatModel | None:
    if not settings.llm_api_key:
        return None
    return OpenAICompatibleModel(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
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


def list_model_providers() -> list[str]:
    return sorted(_providers.keys())
