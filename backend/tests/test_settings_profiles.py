"""v0.6 设置存储：profiles 隔离、v1/v2→v3 迁移、API Key 保留/清除/替换、DPAPI 密文。"""
from __future__ import annotations

import json
from pathlib import Path

from agent_platform.config import settings as env
from agent_platform.infrastructure import secret_store
from agent_platform.services.settings_service import SettingsService


def _service(tmp_path: Path) -> SettingsService:
    return SettingsService(tmp_path / "settings.json")


def test_v1_migration_moves_flat_config_into_profile_and_derives_roles(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"provider": "qwen", "base_url": "https://dashscope", "api_key": "sk-legacy",
                    "model": "qwen3.7-plus", "vision_model": "qwen3.8-omni-flash"}),
        encoding="utf-8",
    )
    service = _service(tmp_path)
    cfg = service.load()
    assert cfg["provider"] == "qwen" and cfg["model"] == "qwen3.7-plus"
    assert cfg["api_key"] == "sk-legacy"  # 明文可读回（透明迁移）
    # v2 语义在 v3 里等价复现：reasoning 取 active+model，vision 取 vision_model
    roles = service.roles_view()
    assert roles["reasoning"] == {"provider": "qwen", "model": "qwen3.7-plus", "usable": True}
    assert roles["vision"]["provider"] == "qwen" and roles["vision"]["model"] == "qwen3.8-omni-flash"
    assert roles["image_gen"] is None
    # 公开视图永远不含 Key
    view = json.dumps(service.public_config()) + json.dumps(service.profiles_view()) + json.dumps(roles)
    assert "sk-legacy" not in view and '"api_key"' not in view
    # 读取只透明迁移；下一次保存才写成 v3 结构（Key 加密落盘、仍可解回）
    service.save({"provider": "qwen", "api_key": None})
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["version"] == 3
    stored = body["profiles"]["qwen"]["api_key"]
    assert stored.startswith("enc:v1:") or stored == "sk-legacy"  # 非 Windows 平台透传明文
    assert secret_store.decrypt(stored) == "sk-legacy"


def test_profiles_isolated_and_roles_can_span_providers(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.save({"provider": "deepseek", "api_key": "sk-ds",
                  "roles": {"reasoning": {"provider": "deepseek", "model": "deepseek-v4-pro"}}})
    service.save({"provider": "qwen", "api_key": "sk-qw",
                  "roles": {"vision": {"provider": "qwen", "model": "qwen3.8-omni-flash"}}})
    # 推理角色用 DeepSeek 的凭据，识图角色用百炼的凭据——跨厂商组合、互不串 Key
    reasoning = service.resolve_role("reasoning")
    vision = service.resolve_role("vision")
    assert reasoning["api_key"] == "sk-ds" and reasoning["model"] == "deepseek-v4-pro"
    assert vision["api_key"] == "sk-qw"
    assert vision["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert service.resolve_role("image_gen") is None
    # 只提交 roles 里的一个键：其余角色原样保留
    service.save({"provider": "qwen", "roles": {"image_gen": {"provider": "qwen", "model": "qwen-image-2.0-pro"}}})
    assert service.resolve_role("vision")["model"] == "qwen3.8-omni-flash"
    assert service.resolve_role("image_gen")["model"] == "qwen-image-2.0-pro"
    # 取消配置：null
    service.save({"provider": "qwen", "roles": {"vision": None}})
    assert service.resolve_role("vision") is None


def test_role_model_falls_back_to_preset_default(tmp_path: Path) -> None:
    service = _service(tmp_path)
    # 角色只选了供应商没填模型名 → 预设默认顶上；vision 无默认则按未配置处理
    service.save({"provider": "zhipu", "api_key": "sk-zp", "roles": {"reasoning": {"provider": "zhipu"}}})
    assert service.resolve_role("reasoning")["model"] == "glm-5-turbo"
    service.save({"provider": "zhipu", "roles": {"vision": {"provider": "zhipu"}}})
    assert service.resolve_role("vision")["model"] == "glm-5.3-flash"
    service.save({"provider": "custom", "roles": {"vision": {"provider": "custom"}}})
    assert service.resolve_role("vision") is None


def test_api_key_keep_clear_replace_semantics(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.save({"provider": "zhipu", "api_key": "sk-a"})
    service.save({"provider": "zhipu", "api_key": None})  # 保留
    assert service._profile_credentials("zhipu", service._data())[1] == "sk-a"
    service.save({"provider": "zhipu", "api_key": "sk-b"})  # 替换
    assert service._profile_credentials("zhipu", service._data())[1] == "sk-b"
    service.save({"provider": "zhipu", "api_key": ""})  # 清除
    assert service._profile_credentials("zhipu", service._data())[1] == ""
    assert not service.profiles_view()["zhipu"]["has_api_key"]


def test_env_key_never_leaks_to_other_providers(tmp_path: Path) -> None:
    service = _service(tmp_path)
    # 只给千问建角色、不存 Key：.env 的 DeepSeek Key 不应串到千问的解析结果上
    service.save({"provider": "qwen", "roles": {"reasoning": {"provider": "qwen"}}})
    reasoning = service.resolve_role("reasoning")
    assert reasoning["model"] == "qwen3.7-plus"
    if env.llm_provider != "qwen":
        assert reasoning["api_key"] == ""
