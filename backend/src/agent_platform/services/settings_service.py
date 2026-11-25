"""用户设置用例：凭据档案（profiles）与干活角色（roles）两层配置（v0.6 起 v3 存储）。

存储布局 `data/settings.json`（gitignored）：

    {"version": 3, "active": "deepseek",
     "profiles": {"<provider>": {"base_url", "api_key(密文)", "model", "vision_model"}},   # 后两字段为 v2 遗留，读取兼容
     "roles": {
        "reasoning": {"provider": "...", "model": "..."},      # 主模型：对话/任务/工具循环/记忆提炼
        "vision":    {"provider": "...", "model": "..."} | null,  # 识图：附件图片描述
        "image_gen": {"provider": "...", "model": "..."} | null,   # 生图：generate_image 工具
        "embedding": {"provider": "...", "model": "..."} | null    # 嵌入：知识库向量检索（null=关闭，纯关键词）
     },
     "memory_enabled": true}

设计要点：
- **profiles = 凭据**（每供应商各自的 Base URL 与 Key，互不覆写）；**roles = 分工**（谁干哪类活）。
  角色引用某个供应商的凭据即可跨厂商组合：推理用 DeepSeek、识图用百炼、生图用智谱——各用各的 Key；
- 角色模型名解析优先级：role.model > 该供应商在 .env 的同名配置（仅 reasoning + 同供应商时）> 预设默认；
- **API Key 经 DPAPI 加密落盘**（infrastructure/secret_store），HTTP 层只回 has_api_key 布尔、永不回显明文；
- api_key 保存语义：None=保留原值，""=清除，非空=替换；roles 里出现哪个键就整体替换哪个角色（null=取消配置）；
- v1（单配置）/v2（profiles 无 roles）旧文件在读取时自动派生 roles：reasoning 取当时的 active+model，
  vision 取 vision_model（空则 null），image_gen/embedding=null——行为与旧版本完全一致；下一次保存写成 v3。
前端设置页通过 /api/settings 读写这里的配置。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from agent_platform.config import settings
from agent_platform.infrastructure import secret_store

# 内置国产模型预设（前端设置页展示 + 下拉候选）
# models/vision_models/image_models/embedding_models 分别是四个角色的下拉候选；model 是 reasoning 的默认模型名。
# 约束（v0.6.1，问题清单 #2）：**vision_models ⊆ models**——视觉模型都能对话/推理，主模型下拉必须看得到它们；
# image_models 走独立 images 端点，不是聊天模型，允许不在 models 里。
# 清单按 2026-11 各家官方文档核对（DeepSeek 价格页 / 阿里云百炼模型列表 / 智谱模型概览），
# 另含一次百炼 /models 实时目录实测；厂商随时调整，设置页“获取可用模型”可拉取 Key 下实时列表兜底。
PRESETS = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "vision_model": "",
        "models": ["deepseek-flash", "deepseek-v4-pro"],
        # deepseek-flash（V4.1-Flash）原生支持图像输入；deepseek-v4-pro 为纯文本；官方无生图模型
        "vision_models": ["deepseek-flash"],
        "image_models": [],
        # DeepSeek 官方没有嵌入端点，知识库向量检索需另配一家的 embedding 角色
        "embedding_models": [],
        "api_url": "https://platform.deepseek.com/",
    },
    "qwen": {
        "label": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.7-plus",
        "vision_model": "",
        "models": ["qwen3.8-flash", "qwen3.7-plus", "qwen4-max", "qwen3.8-omni-flash"],
        # qwen4-max / qwen3.7-plus 原生支持图像输入；qwen3.8-omni-flash 为独立多模态（图/视频/音）
        "vision_models": ["qwen3.8-omni-flash", "qwen3.7-plus", "qwen4-max"],
        # 2026-11 实测（qwen 真实 Key，走适配后的 DashScope 原生 multimodal-generation 同步端点）：
        # 三个模型全部真实出图——qwen-image-2.0-pro 18.6s / qwen-image-3.0-pro 62.9s（慢但可用）/ wan2.7-image-pro 27.4s；
        # 注：各家兼容模式 /images/generations 对这批 id 一律 404，imagegen 已按域名改走原生端点
        "image_models": ["qwen-image-2.0-pro", "qwen-image-3.0-pro", "wan2.7-image-pro"],
        # DashScope 兼容模式 /embeddings：v4 支持多语言/任务指令（默认 1024 维），v3 为其前代
        "embedding_models": ["text-embedding-v4", "text-embedding-v3"],
        "api_url": "https://bailian.console.aliyun.com/",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5-turbo",
        "vision_model": "",
        "models": ["glm-5.3", "glm-5.2", "glm-5.1", "glm-5-turbo", "glm-5", "glm-4.7-flash",
                   "glm-5.3-flash", "glm-5v-turbo", "glm-4.6v"],
        "vision_models": ["glm-5.3-flash", "glm-5v-turbo", "glm-4.6v"],
        # 2026-11 实测：本机无智谱 Key，glm-image 未能真实调用（端点是否兼容 OpenAI 格式未知）；
        # 拿到 Key 后需实测再决定是否保留此候选
        "image_models": ["glm-image"],
        "embedding_models": ["embedding-3"],
        "api_url": "https://open.bigmodel.cn/",
    },
    "custom": {
        "label": "自定义",
        "base_url": "",
        "model": "",
        "vision_model": "",
        "models": [],
        "vision_models": [],
        "image_models": [],
        "embedding_models": [],
        "api_url": "",
    },
}

ROLES = ("reasoning", "vision", "image_gen", "embedding")
#: 角色下拉候选取自预设的哪个键
ROLE_OPTION_KEY = {"reasoning": "models", "vision": "vision_models",
                   "image_gen": "image_models", "embedding": "embedding_models"}
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


def _merge_role(saved: object) -> dict | None:
    """roles 条目规范化：{provider, model} 或 None（null=该角色未配置）。"""
    if not isinstance(saved, dict):
        return None
    provider = str(saved.get("provider") or "").strip()
    if not provider:
        return None
    return {"provider": provider, "model": str(saved.get("model") or "").strip()}


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
        """统一规范成 v3 结构；v1/v2 旧文件在此透明升级（roles 自动派生，行为不变）。"""
        if isinstance(raw.get("profiles"), dict):
            profiles = {str(pid): _merge_profile(prof) for pid, prof in raw["profiles"].items()}
            active = str(raw.get("active") or settings.llm_provider)
            if isinstance(raw.get("roles"), dict):
                roles = {role: _merge_role(raw["roles"].get(role)) for role in ROLES}
            else:
                roles = self._derive_roles(active, profiles)
            return {"version": 3, "active": active, "profiles": profiles, "roles": roles,
                    "memory_enabled": raw.get("memory_enabled")}

        # v1：顶层单配置 + 明文 Key
        provider = str(raw.get("provider") or settings.llm_provider).strip() or settings.llm_provider
        legacy = _merge_profile(raw)
        if legacy["api_key"]:
            legacy["api_key"] = secret_store.encrypt(legacy["api_key"])
        profiles = {provider: legacy} if any(legacy.values()) else {}
        return {"version": 3, "active": provider, "profiles": profiles,
                "roles": self._derive_roles(provider, profiles),
                "memory_enabled": raw.get("memory_enabled")}

    @staticmethod
    def _derive_roles(active: str, profiles: dict) -> dict:
        """v2 语义 → roles：主模型=active 档案+model 名；识图=同档案+vision_model（空则不配）。"""
        profile = _merge_profile(profiles.get(active))
        vision = profile["vision_model"]
        return {
            "reasoning": {"provider": active, "model": profile["model"]},
            "vision": {"provider": active, "model": vision} if vision else None,
            "image_gen": None,
            "embedding": None,  # v0.6.2 新增角色：旧配置派生时保持关闭，行为不变
        }

    def _data(self) -> dict:
        return self._migrate(self._read_raw())

    # ---------- 角色解析（核心） ----------

    def _profile_credentials(self, provider: str, data: dict) -> tuple[str, str]:
        """该供应商凭据 (base_url, 明文 api_key)。.env 兜底只对 .env 那一家生效，绝不串 Key。"""
        profile = _merge_profile(data["profiles"].get(provider))
        preset = PRESETS.get(provider)
        base_url = profile["base_url"]
        api_key = secret_store.decrypt(profile["api_key"])
        if provider == settings.llm_provider:
            base_url = base_url or settings.llm_base_url
            api_key = api_key or settings.llm_api_key
        elif preset:
            base_url = base_url or preset["base_url"]
        return base_url, api_key

    def resolve_role(self, role: str) -> dict | None:
        """角色 → 完整可用配置 {provider, base_url, api_key, model}；未配置/无模型名可用时 None。

        模型名解析：role.model > .env LLM_MODEL（仅 reasoning 且 provider==.env 那家）> 预设默认。
        """
        if role not in ROLES:
            return None
        data = self._data()
        entry = data["roles"].get(role)
        if not entry:
            return None
        provider = entry["provider"]
        model = entry["model"]
        if not model and role == "reasoning" and provider == settings.llm_provider:
            model = settings.llm_model
        if not model:
            preset = PRESETS.get(provider)
            if role == "reasoning":
                model = (preset or {}).get("model", "")
            else:
                options = (preset or {}).get(ROLE_OPTION_KEY[role], [])
                model = options[0] if options else ""
        if not model:
            return None
        base_url, api_key = self._profile_credentials(provider, data)
        return {"provider": provider, "base_url": base_url, "api_key": api_key, "model": model}

    # ---------- 对外视图 ----------

    def load(self) -> dict:
        """兼容视图（memory 取 memory_enabled、discover 取凭据）：reasoning 生效配置 + active 档案。"""
        data = self._data()
        reasoning = self.resolve_role("reasoning") or {}
        base_url, api_key = self._profile_credentials(data["active"], data)
        vision = self.resolve_role("vision")
        return {
            "provider": data["active"],
            "base_url": base_url,
            "api_key": api_key,
            "model": reasoning.get("model", ""),
            "vision_model": vision["model"] if vision else "",
            "memory_enabled": bool(
                data["memory_enabled"] if data["memory_enabled"] is not None else settings.memory_enabled
            ),
        }

    def public_config(self) -> dict:
        """给旧视图（App 顶栏指示、MemoryPanel 开关）：永不带 Key。"""
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
        """凭据卡片视图（不含 Key 明文）。v2 的 model/vision_model 一并回显供参考。"""
        data = self._data()
        view: dict = {}
        for pid in [*PRESETS, *data["profiles"]]:
            if pid in view:
                continue
            profile = _merge_profile(data["profiles"].get(pid))
            _, api_key = self._profile_credentials(pid, data)
            view[pid] = {
                "base_url": profile["base_url"],
                "model": profile["model"],
                "vision_model": profile["vision_model"],
                "has_api_key": bool(api_key),
            }
        return view

    def roles_view(self) -> dict:
        """角色卡片视图：{role: {provider, model, usable(有 Key)} | null}，永不带 Key。"""
        data = self._data()
        view = {}
        for role in ROLES:
            entry = data["roles"].get(role)
            if not entry:
                view[role] = None
                continue
            _, api_key = self._profile_credentials(entry["provider"], data)
            view[role] = {"provider": entry["provider"], "model": entry["model"], "usable": bool(api_key)}
        return view

    # ---------- 保存 ----------

    def save(self, payload: dict) -> dict:
        """写凭据档案（provider+base_url+api_key）与/或角色（roles 键出现才动）。

        api_key 语义：缺省/None=保留，""=清除，非空=替换；
        roles：载荷里出现的键整体替换对应角色（{provider,model} 或 null），未出现的保持原样。
        只动 payload.provider 对应的凭据档案，其他供应商原样保留（隔离）。
        """
        with self._lock:
            data = self._data()
            provider = str(payload.get("provider") or "").strip() or data["active"]
            data["active"] = provider
            profile = _merge_profile(data["profiles"].get(provider))
            if payload.get("base_url") is not None:
                profile["base_url"] = str(payload["base_url"]).strip()
            if "api_key" in payload and payload["api_key"] is not None:
                key = str(payload["api_key"]).strip()
                profile["api_key"] = secret_store.encrypt(key) if key else ""
            data["profiles"][provider] = profile
            roles_payload = payload.get("roles")
            if isinstance(roles_payload, dict):
                for role in ROLES:
                    if role in roles_payload:
                        data["roles"][role] = _merge_role(roles_payload[role])
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
