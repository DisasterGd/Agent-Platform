"""用户设置用例：模型配置的读写（本地 JSON 持久化，gitignored）。

模型配置优先级：用户设置（data/settings.json）> .env。
前端设置页通过 /api/settings 读写这里的配置。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from agent_platform.config import settings

# 内置国产模型预设（前端设置页展示 + 一键填入）
PRESETS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "vision_model": "",
        "api_url": "https://platform.deepseek.com/",
    },
    "qwen": {
        "label": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "vision_model": "qwen-vl-plus",
        "api_url": "https://bailian.console.aliyun.com/",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-plus",
        "vision_model": "glm-4v-plus",
        "api_url": "https://open.bigmodel.cn/",
    },
    "custom": {
        "label": "自定义",
        "base_url": "",
        "model": "",
        "vision_model": "",
        "api_url": "",
    },
}

CONFIG_FIELDS = ("provider", "base_url", "api_key", "model", "vision_model")


class SettingsService:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _defaults(self) -> dict:
        return {
            "provider": settings.llm_provider,
            "base_url": settings.llm_base_url,
            "api_key": settings.llm_api_key,
            "model": settings.llm_model,
            "vision_model": "",
        }

    def _read(self) -> dict:
        if self.path.is_file():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def load(self) -> dict:
        config = self._defaults()
        saved = self._read()
        for key in CONFIG_FIELDS:
            if key in saved:
                config[key] = saved[key]
        # v0.4：自动记忆开关（默认跟随 .env 的全局配置）
        config["memory_enabled"] = bool(saved.get("memory_enabled", settings.memory_enabled))
        return config

    def save(self, payload: dict) -> dict:
        config = {key: str(payload.get(key) or "").strip() for key in CONFIG_FIELDS}
        memory_enabled = payload.get("memory_enabled")
        if memory_enabled is None:
            # 未显式提交时保持已保存的开关，避免“模型页保存”把记忆设置重置
            memory_enabled = self.load().get("memory_enabled", settings.memory_enabled)
        config["memory_enabled"] = bool(memory_enabled)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        return config


_service: SettingsService | None = None


def get_settings_service() -> SettingsService:
    global _service
    if _service is None:
        _service = SettingsService(Path(settings.storage_dir) / "settings.json")
    return _service
