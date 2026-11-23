"""用户设置用例：按供应商隔离的模型配置（v0.5.2 起为 profiles 存储结构）。

存储布局 `data/settings.json`（gitignored）：

    {"version": 2, "active": "deepseek",
     "profiles": {"<provider>": {"base_url", "api_key(密文)", "model", "vision_model"}},
     "memory_enabled": true}

设计要点（对应 v0.5.2 修复清单）：
- **profile 之间互相隔离**：切换/保存某个供应商只动它自己的档案，不覆写其他供应商已存的模型与 Key；
- **API Key 经 DPAPI 加密落盘**（infrastructure/secret_store），HTTP 层只回 has_api_key 布尔、永不回显明文；
- api_key 保存语义：None=保留原值，""=清除，非空=替换；
- v1 单配置 + 明文 Key 的旧文件在读取时自动迁移，下一次保存写成 v2；
- 生效优先级：active profile 字段 > .env（仅当 active 就是 .env 的 LLM_PROVIDER 时回退）。
前端设置页通过 /api/settings 读写这里的配置。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from agent_platform.config import settings
from agent_platform.infrastructure import secret_store

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

PROFILE_FIELDS = ("base_url", "api_key", "model", "vision_model")


def _blank_profile() -> dict:
    return {field: "" for field in PROFILE_FIELDS}


def _merge_profile(saved: dict | None) -> dict:
    """缺字段/未知字段都兜得住：只取 PROFILE_FIELDS，缺失按空串。"""
    profile = _blank_profile()
    if isinstance(saved, dict):
        for field in PROFILE_FIELDS:
            profile[field] = str(saved.get(field) or "")
    return profile


class SettingsService:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    # ---------- 读取与迁移 ----------

    def _read_raw(self) -> dict:
        if self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    return loaded
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _migrate(self, raw: dict) -> dict:
        """v1（单配置 + 明文 Key）→ v2（profiles 隔离 + 密文）。v2 原样规范化返回。"""
        if isinstance(raw.get("profiles"), dict):
            profiles = {}
            for pid, prof in raw["profiles"].items():
                profiles[str(pid)] = _merge_profile(prof)
            return {
                "version": 2,
                "active": str(raw.get("active") or settings.llm_provider),
                "profiles": profiles,
                "memory_enabled": raw.get("memory_enabled"),
            }
        provider = str(raw.get("provider") or settings.llm_provider).strip() or settings.llm_provider
        legacy = _merge_profile(raw)
        if legacy["api_key"]:
            legacy["api_key"] = secret_store.encrypt(legacy["api_key"])  # 明文就地升级，读取路径同样只见密文
        return {
            "version": 2,
            "active": provider,
            "profiles": {provider: legacy} if any(legacy.values()) else {},
            "memory_enabled": raw.get("memory_enabled"),
        }

    def _data(self) -> dict:
        return self._migrate(self._read_raw())

    # ---------- 对外视图 ----------

    def load(self) -> dict:
        """内部生效配置（含解开的 Key）：active profile > .env（仅当 provider 与 .env 一致）> 预设默认。

        仅供 factory/memory 使用——解开的明文 Key 严禁从这里流到 HTTP 响应。
        """
        data = self._data()
        provider = data["active"]
        profile = _merge_profile(data["profiles"].get(provider))
        cfg = {
            "provider": provider,
            "base_url": profile["base_url"],
            "api_key": secret_store.decrypt(profile["api_key"]),
            "model": profile["model"],
            "vision_model": profile["vision_model"],
        }
        preset = PRESETS.get(provider)
        if provider == settings.llm_provider:
            # .env 兜底只对“同一个供应商”有意义，否则会把 DeepSeek 的 Key/模型名发给百炼
            cfg["base_url"] = cfg["base_url"] or settings.llm_base_url
            cfg["api_key"] = cfg["api_key"] or settings.llm_api_key
            cfg["model"] = cfg["model"] or settings.llm_model
        elif preset:
            cfg["base_url"] = cfg["base_url"] or preset["base_url"]
            cfg["model"] = cfg["model"] or preset["model"]
        cfg["memory_enabled"] = bool(
            data["memory_enabled"] if data["memory_enabled"] is not None else settings.memory_enabled
        )
        return cfg

    def public_config(self) -> dict:
        """给设置页的当前生效视图：永不带 Key，只带 has_api_key。"""
        cfg = self.load()
        return {
            "provider": cfg["provider"],
            "base_url": cfg["base_url"],
            "model": cfg["model"],
            "vision_model": cfg["vision_model"],
            "has_api_key": bool(cfg["api_key"]),
            "memory_enabled": cfg["memory_enabled"],
        }

    def profiles_view(self) -> dict:
        data = self._data()
        view = {}
        for pid in [*PRESETS, *data["profiles"]]:
            if pid in view:
                continue
            profile = _merge_profile(data["profiles"].get(pid))
            view[pid] = {
                "base_url": profile["base_url"],
                "model": profile["model"],
                "vision_model": profile["vision_model"],
                "has_api_key": bool(secret_store.decrypt(profile["api_key"])),
            }
        return view

    # ---------- 保存 ----------

    def save(self, payload: dict) -> dict:
        """写 active 供应商的档案。api_key 语义：缺省/None=保留，""=清除，非空=替换。

        只动 payload.provider 对应的 profile，其他供应商的档案原样保留（隔离）。
        """
        with self._lock:
            data = self._data()
            provider = str(payload.get("provider") or "").strip() or data["active"]
            data["active"] = provider
            profile = _merge_profile(data["profiles"].get(provider))
            for field in ("base_url", "model", "vision_model"):
                if payload.get(field) is not None:
                    profile[field] = str(payload[field]).strip()
            if "api_key" in payload and payload["api_key"] is not None:
                key = str(payload["api_key"]).strip()
                profile["api_key"] = secret_store.encrypt(key) if key else ""
            data["profiles"][provider] = profile
            if payload.get("memory_enabled") is not None:
                data["memory_enabled"] = bool(payload["memory_enabled"])
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.public_config()


_service: SettingsService | None = None


def get_settings_service() -> SettingsService:
    global _service
    if _service is None:
        _service = SettingsService(Path(settings.storage_dir) / "settings.json")
    return _service
