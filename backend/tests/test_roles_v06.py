"""v0.6 角色化装配：factory 按角色建模型、生图端点双响应形状、generate_image 工具。"""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest

from agent_platform.config import settings
from agent_platform.infrastructure.imagegen import ImageGenError, generate_image
from agent_platform.models import factory
from agent_platform.services import settings_service
from agent_platform.tools.builtin import images as images_tool

PNG = b"\x89PNG\r\n\x1a\n" + b"pixeldata" * 4


@pytest.fixture()
def service(tmp_path: Path, monkeypatch) -> settings_service.SettingsService:
    """把模块级单例临时换成 tmp 路径的服务（测试间互不污染）。"""
    svc = settings_service.SettingsService(tmp_path / "settings.json")
    monkeypatch.setattr(settings_service, "_service", svc)
    return svc


# ---------- factory：按角色装配 ----------

def test_factory_builds_chat_models_from_roles(service: settings_service.SettingsService) -> None:
    service.save({
        "provider": "deepseek", "api_key": "sk-ds",
        "roles": {"reasoning": {"provider": "deepseek", "model": "deepseek-v4-pro"},
                  "vision": {"provider": "qwen", "model": "qwen3.8-omni-flash"}},
    })
    service.save({"provider": "qwen", "api_key": "sk-qw"})
    main = factory.create_model()
    assert main is not None and main.model == "deepseek-v4-pro"
    vision = factory.create_vision_model()
    assert vision is not None and vision.model == "qwen3.8-omni-flash"
    # 识图角色引用百炼凭据：客户端 base_url 指向百炼，而主模型仍是 DeepSeek
    assert "dashscope" in str(vision.client.base_url)
    assert "deepseek.com" in str(main.client.base_url)
    # 生图未配置 → None
    assert factory.create_image_config() is None


def test_factory_no_key_means_none(service: settings_service.SettingsService) -> None:
    service.save({"provider": "qwen", "roles": {"reasoning": {"provider": "qwen", "model": "qwen3.7-plus"}}})
    if settings.llm_provider != "qwen":  # .env 的 Key 不算到别家头上
        assert factory.create_model() is None


# ---------- infrastructure/imagegen：双响应形状 ----------

def _run(handler, key="sk-x"):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await generate_image("https://gen.example/v1/", key, "img-model", "一只戴帽子的柴犬", client=client)
    return asyncio.run(go())


def test_imagegen_b64_json_shape() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("Authorization", "")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})

    data, mime = _run(handler)
    assert data == PNG and mime == "image/png"
    assert seen["path"] == "/v1/images/generations"  # 尾部斜杠归一
    assert seen["auth"] == "Bearer sk-x"
    assert seen["body"]["model"] == "img-model" and seen["body"]["n"] == 1


def test_imagegen_url_shape_downloads() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example/a.png"}]})
        assert str(request.url) == "https://cdn.example/a.png"
        return httpx.Response(200, content=PNG)

    data, mime = _run(handler)
    assert data == PNG and mime == "image/png"


def test_imagegen_rejects_bad_inputs() -> None:
    def ok_post(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"data": [{"url": "http://insecure.example/a.png"}]})
        return httpx.Response(200, content=PNG)

    with pytest.raises(ImageGenError):
        _run(ok_post)  # http:// 图片地址拒收
    with pytest.raises(ImageGenError):
        _run(lambda request: httpx.Response(200, json={"result": []}))
    with pytest.raises(ImageGenError):
        _run(lambda request: httpx.Response(400, json={"error": {"message": "quota exceeded"}}))
    with pytest.raises(ImageGenError):
        _run(lambda request: httpx.Response(200, json={"data": [{"b64_json": "a"}]}))  # 非法 base64（padding 错）


def test_imagegen_error_message_contains_server_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "size not supported"}})

    try:
        _run(handler)
    except ImageGenError as exc:
        assert "size not supported" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("应抛 ImageGenError")


# ---------- tools/generate_image ----------

def test_generate_image_tool_requires_role_config(monkeypatch) -> None:
    monkeypatch.setattr(images_tool, "create_image_config", lambda: None)
    result = asyncio.run(images_tool.generate_image_tool(prompt="画个圆"))
    payload = json.loads(result.content)
    assert payload["ok"] is False and "设置" in payload["error"]
    assert result.artifacts == []


def test_generate_image_tool_produces_artifact(monkeypatch) -> None:
    cfg = {"provider": "qwen", "base_url": "https://dashscope/compatible-mode/v1", "api_key": "sk-qw",
           "model": "qwen-image-2.0-pro"}

    async def fake_generate(base_url, api_key, model, prompt, size="1024x1024"):
        assert base_url == cfg["base_url"] and model == cfg["model"]
        assert size == "768x1024"
        return PNG, "image/png"

    monkeypatch.setattr(images_tool, "create_image_config", lambda: cfg)
    monkeypatch.setattr(images_tool, "generate_image", fake_generate)
    result = asyncio.run(images_tool.generate_image_tool(prompt="竖版海报", size="768x1024", name="poster_spring"))

    payload = json.loads(result.content)
    assert payload["ok"] is True and payload["filename"].startswith("poster_spring")
    assert payload["filename"].endswith(".png")
    artifact = result.artifacts[0]
    assert artifact["kind"] == "image" and artifact["category"] == "generated"
    path = Path(settings.storage_dir) / "generated" / artifact["stored_name"]
    assert path.is_file() and path.read_bytes() == PNG
    path.unlink(missing_ok=True)


def test_generate_image_tool_surface_failure(monkeypatch) -> None:
    async def boom(*a, **k):
        raise ImageGenError("HTTP 402：余额不足")

    monkeypatch.setattr(images_tool, "create_image_config", lambda: {"provider": "qwen", "base_url": "b",
                                                                      "api_key": "k", "model": "m"})
    monkeypatch.setattr(images_tool, "generate_image", boom)
    result = asyncio.run(images_tool.generate_image_tool(prompt="x"))
    payload = json.loads(result.content)
    assert payload["ok"] is False and "余额不足" in payload["error"]
