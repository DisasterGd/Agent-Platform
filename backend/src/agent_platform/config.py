from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（backend/src/agent_platform/config.py 往上三层）
_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _ROOT / ".env"


class Settings(BaseSettings):
    app_name: str = "Agent Platform"
    app_env: str = "development"
    api_v1_prefix: str = "/api"
    frontend_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    database_url: str
    dev_user_id: int = 1

    # 大模型（OpenAI 兼容接口，默认指向 DeepSeek）
    # llm_provider 用于在 models.factory 中选择适配器，未来多模态模型在此登记。
    # llm_model 仅作 .env 兜底：设置页（data/settings.json）优先。deepseek-chat 已下线，
    # 2026-11 官方在服：deepseek-flash（V4.1-Flash，原生视觉）/ deepseek-v4-pro（纯文本）。
    llm_provider: str = "deepseek"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-flash"
    llm_temperature: float = 0.7

    # 联网搜索（tools/builtin/search.py 调用）
    # search_provider: auto（默认，DuckDuckGo → Bing 网页兜底，零配置）| duckduckgo | bing_scrape | bing | tavily
    # bing / tavily 需要 search_api_key
    search_provider: str = "auto"
    search_api_key: str = ""
    search_max_results: int = 5

    # 文件存储根目录（上传文件 + Agent 生成的文件），未来可替换为对象存储。
    storage_dir: str = str(_ROOT / "data")

    # ---- v0.7 账号体系 ----
    # auth_mode: local（默认）=单用户免登录，行为与 v0.6 完全一致；
    #            cloud=邮箱验证码登录、按用户隔离数据/文件/设置——差异只在配置与认证，不在代码分叉。
    auth_mode: str = "local"
    # cloud 模式：首个管理员邮箱（该邮箱注册时自动 is_admin=1）
    admin_email: str = ""
    # 登录会话有效期（天，滑动续期）；cookie 名固定为 ap_session
    session_ttl_days: int = 30
    # cloud 模式下加密用户 API Key 的服务密钥（Fernet 派生源；cloud 必配，local 不用——local 走 DPAPI）
    service_secret: str = ""

    # ---- v0.8 部署加固 ----
    # MySQL 连接池（按 uvicorn worker 数一起算：worker × (pool_size + max_overflow) ≤ MySQL max_connections）
    db_pool_size: int = 10
    db_max_overflow: int = 20
    # 全站 API 限流（每 IP 每分钟请求数；0=关闭。本地单用户 120 足够宽裕；上线防单点刷爆）
    rate_limit_per_minute: int = 120

    # ---- 邮件（验证码通道，v0.7）----
    # mail_provider: console（默认，验证码打印到控制台/日志，本地调试 cloud 模式用）| smtp
    # smtp：QQ/163 邮箱授权码即可（smtp.qq.com:465 / smtp.163.com:465），零新依赖
    mail_provider: str = "console"
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = ""

    # 三级记忆（v0.4）
    # memory_enabled：总开关（上下文注入 + 对话后自动提炼）；用户也可在设置页关闭自动记忆
    memory_enabled: bool = True
    memory_char_budget: int = 4000         # 注入系统提示词的记忆字符上限
    context_compress_chars: int = 9000     # 会话历史总字数超过该值触发自动压缩
    context_keep_recent: int = 6           # 压缩时保留最近 N 条消息原样

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.frontend_origins.split(",") if item.strip()]

    @property
    def model_configured(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def uploads_dir(self) -> Path:
        return Path(self.storage_dir) / "uploads"

    @property
    def generated_dir(self) -> Path:
        return Path(self.storage_dir) / "generated"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
