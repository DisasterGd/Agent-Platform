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
# model/vision_model 是点预设时填入的默认值；models/vision_models 是“模型/视觉模型”输入框的下拉候选。
# 清单按 2026-11 各家官方文档核对（DeepSeek 价格页 / 阿里云百炼模型列表 / 智谱模型概览）；
# 厂商随时调整，设置页的“获取可用模型”（GET {base_url}/models）可拉取你 Key 下的实时列表兜底。
PRESETS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "vision_model": "",
        "models": ["deepseek-flash", "deepseek-v4-pro"],
        # deepseek-flash（V4.1-Flash）原生支持图像输入；deepseek-v4-pro 为纯文本
        "vision_models": ["deepseek-flash"],
        "api_url": "https://platform.deepseek.com/",
    },
    "qwen": {
        "label": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.7-plus",
        "vision_model": "",
        "models": ["qwen3.8-flash", "qwen3.7-plus", "qwen4-max"],
        # qwen4-max / qwen3.7-plus 原生支持图像输入；qwen3.8-omni-flash 为独立多模态（图/视频/音）
        "vision_models": ["qwen3.8-omni-flash", "qwen3.7-plus", "qwen4-max"],
        "api_url": "https://bailian.console.aliyun.com/",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5-turbo",
        "vision_model": "",
        "models": ["glm-5.3", "glm-5.2", "glm-5.1", "glm-5-turbo", "glm-5", "glm-4.7-flash"],
        "vision_models": ["glm-5.3-flash", "glm-5v-turbo", "glm-4.6v"],
        "api_url": "https://open.bigmodel.cn/",
    },
    "custom": {
        "label": "自定义",
        "base_url": "",
        "model": "",
        "vision_model": "",
        "models": [],
        "vision_models": [],
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
