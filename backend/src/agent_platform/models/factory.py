"""根据配置创建模型适配器。"""
from __future__ import annotations

from agent_platform.config import settings
from agent_platform.models.base import ChatModel
from agent_platform.models.openai_compatible import OpenAICompatibleModel


def create_model() -> ChatModel | None:
    """未配置 API Key 时返回 None，由调用方回退到演示模式。"""
    if not settings.llm_api_key:
        return None
    return OpenAICompatibleModel(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
    )
