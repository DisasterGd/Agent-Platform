"""v0.5.1 模型发现接口与预设下拉数据的健全性。

- discover_models：OpenAI 兼容 GET {base_url}/models，用 httpx.MockTransport 全程离线；
- PRESETS：模型清单必须是 2026-11 在服 id（deepseek-chat 等旧名不得回归）。
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from agent_platform.infrastructure.model_discovery import (
    DiscoveryError,
    discover_models,
)
from agent_platform.services.settings_service import PRESETS


async def _discover(
    base_url: str, api_key: str, handler
) -> list[str]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await discover_models(base_url, api_key, client=client)


def test_discover_returns_ids_and_sends_bearer_to_models_endpoint() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(
            200,
            json={"data": [{"id": "deepseek-flash"}, {"id": "deepseek-v4-pro"}, {"id": ""}, {"name": "x"}]},
        )

    models = asyncio.run(_discover("https://api.deepseek.com/", "sk-test", handler))
    assert models == ["deepseek-flash", "deepseek-v4-pro"]  # 空 id / 无 id 项被过滤
    assert seen["url"] == "https://api.deepseek.com/models"  # 尾部斜杠归一
    assert seen["auth"] == "Bearer sk-test"


def test_discover_rejects_bad_inputs_before_network() -> None:
    def never(request: httpx.Request) -> httpx.Response:  # pragma: no cover - 不应被调用
        raise AssertionError("不应发起请求")

    for base, key in [("", "sk-test"), ("ftp://api.deepseek.com", "sk-test"), ("https://api.deepseek.com", " ")]:
        with pytest.raises(DiscoveryError):
            asyncio.run(_discover(base, key, never))


def test_discover_maps_http_error_with_server_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Authentication Fails"}})

    with pytest.raises(DiscoveryError, match=r"401.*Authentication Fails"):
        asyncio.run(_discover("https://api.deepseek.com", "sk-bad", handler))


def test_discover_requires_openai_standard_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": []})  # 缺 data 列表

    with pytest.raises(DiscoveryError):
        asyncio.run(_discover("https://api.deepseek.com", "sk-test", handler))


def test_presets_use_2026_ids_and_carry_dropdown_lists() -> None:
    # deepseek-chat / qwen-plus / glm-4-plus 等历史默认名已下线：不得再出现在任何下拉清单
    retired = {"deepseek-chat", "qwen-plus", "qwen-vl-plus", "glm-4-plus", "glm-4v-plus"}
    for name, preset in PRESETS.items():
        listed = {preset.get("model", ""), preset.get("vision_model", ""), *preset["models"], *preset["vision_models"]}
        assert not (retired & listed), f"{name} 预设含已下线模型名: {retired & listed}"
        if name == "custom":
            continue
        assert preset["model"] in preset["models"], name
        assert preset["models"] and preset["vision_models"], name
    assert PRESETS["deepseek"]["models"] == ["deepseek-flash", "deepseek-v4-pro"]
