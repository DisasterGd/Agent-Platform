"""v0.5.2 设置存储：profiles 隔离、v1→v2 迁移、API Key 保留/清除/替换、DPAPI 密文。"""
from __future__ import annotations

import json
from pathlib import Path

from agent_platform.infrastructure import secret_store
from agent_platform.services.settings_service import SettingsService


def _service(tmp_path: Path) -> SettingsService:
    return SettingsService(tmp_path / "settings.json")


def test_v1_migration_moves_flat_config_into_profile(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"provider": "qwen", "base_url": "https://dashscope", "api_key": "sk-legacy",
                    "model": "qwen3.7-plus", "vision_model": ""}),
        encoding="utf-8",
    )
    service = _service(tmp_path)
    cfg = service.load()
    assert cfg["provider"] == "qwen" and cfg["model"] == "qwen3.7-plus"
    assert cfg["api_key"] == "sk-legacy"  # 明文可读回（透明迁移）
    # 公开视图永远不含 Key
    view = json.dumps(service.public_config()) + json.dumps(service.profiles_view())
    assert "sk-legacy" not in view and '"api_key"' not in view
    # 读取只透明迁移；下一次保存才写成 v2 结构（Key 加密落盘、仍可解回）
    service.save({"provider": "qwen", "api_key": None})
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["version"] == 2
    stored = body["profiles"]["qwen"]["api_key"]
    assert stored.startswith("enc:v1:") or stored == "sk-legacy"  # 非 Windows 平台透传明文
    assert secret_store.decrypt(stored) == "sk-legacy"


def test_profiles_isolated_across_providers(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.save({"provider": "deepseek", "api_key": "sk-ds", "model": "deepseek-flash"})
    service.save({"provider": "qwen", "api_key": "sk-qw", "model": "qwen3.8-flash", "base_url": "https://dashscope"})
    # 切到千问后，生效的是千问档案
    cfg = service.load()
    assert cfg["provider"] == "qwen" and cfg["api_key"] == "sk-qw" and cfg["model"] == "qwen3.8-flash"
    # DeepSeek 档案没被动过
    profiles = service.profiles_view()
    assert profiles["deepseek"]["model"] == "deepseek-flash" and profiles["deepseek"]["has_api_key"]
    # 再切回来：base_url/model 都还在各自的档案里
    service.save({"provider": "deepseek", "api_key": None})
    cfg = service.load()
    assert cfg["provider"] == "deepseek" and cfg["model"] == "deepseek-flash"
    assert cfg["base_url"] == "https://api.deepseek.com"  # 档案空值时预设兜底


def test_api_key_keep_clear_replace_semantics(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.save({"provider": "zhipu", "api_key": "sk-a"})
    service.save({"provider": "zhipu", "api_key": None})  # 保留
    assert service.load()["api_key"] == "sk-a"
    service.save({"provider": "zhipu", "api_key": "sk-b"})  # 替换
    assert service.load()["api_key"] == "sk-b"
    service.save({"provider": "zhipu", "api_key": ""})  # 清除
    assert service.load()["api_key"] in ("", None) or not service.load()["api_key"]
    assert not service.profiles_view()["zhipu"]["has_api_key"]


def test_env_fallback_only_for_same_provider(tmp_path: Path) -> None:
    service = _service(tmp_path)
    # 只给千问存模型名、不存 Key：.env 的 DeepSeek Key 不应串到千问档案上
    service.save({"provider": "qwen", "model": "qwen3.7-plus"})
    cfg = service.load()
    assert cfg["model"] == "qwen3.7-plus"
    from agent_platform.config import settings as env

    if env.llm_provider != "qwen":
        assert cfg["api_key"] != env.llm_api_key or not env.llm_api_key
