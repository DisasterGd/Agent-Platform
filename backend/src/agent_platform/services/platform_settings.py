"""v0.8 部署级配置：deployment_settings 表 + 邮件/搜索通道的运行期配置。

产品原则（memory: config-layering-principle）：可变配置一律前端界面化，.env 只留启动级。
本服务是"邮件通道 + 搜索源"两块业务配置的唯一真源：
- 存储按 name 存 JSON（deployment_settings 表，local/cloud 同一套——本地 MySQL 也在本机）；
- 敏感字段（SMTP 密码/搜索 API Key）入库前经 secret_store 加密（按 auth_mode 选后端），永不回显；
- 每字段未配置时回退 .env 同名值（部署者没在界面填之前行为与 v0.7 完全一致——零破坏迁移）；
- 写入语义与模型 Key 一致：密码字段 缺省=保留 / 空串=清除 / 非空=替换。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from agent_platform.config import settings
from agent_platform.infrastructure import secret_store
from agent_platform.infrastructure.mail.base import MailProvider
from agent_platform.infrastructure.mail.console import ConsoleProvider
from agent_platform.infrastructure.mail.smtp import SMTPProvider
from agent_platform.repositories.deployment_settings import DeploymentSettingsRepository

MAIL_KEY = "mail"
SEARCH_KEY = "search"

MAIL_PROVIDERS = ("console", "smtp")
SEARCH_PROVIDERS = ("auto", "duckduckgo", "bing_scrape", "bing", "tavily")


class PlatformConfigError(Exception):
    """带用户可读信息的平台配置错误（路由层转 400）。"""


# ---------- 邮件通道 ----------

def effective_mail_config(db: Session) -> dict:
    """生效的邮件配置：deployment_settings["mail"] 逐字段覆盖，缺字段回退 .env。密码已解密。"""
    stored = DeploymentSettingsRepository(db).get(MAIL_KEY) or {}
    return {
        "provider": (stored.get("provider") or settings.mail_provider or "console").strip().lower(),
        "host": stored.get("host") or settings.smtp_host,
        "port": int(stored.get("port") or settings.smtp_port or 465),
        "user": stored.get("user") or settings.smtp_user,
        "password": secret_store.decrypt(stored.get("password_enc") or "") or settings.smtp_password,
        "from_addr": stored.get("from_addr") or settings.mail_from or settings.smtp_user,
    }


def get_mail_provider(db: Session) -> MailProvider:
    """按生效配置组装邮件通道（每次调用实时解析——界面改完即生效，无需重启）。"""
    cfg = effective_mail_config(db)
    if cfg["provider"] == "smtp":
        return SMTPProvider(host=cfg["host"], port=cfg["port"], user=cfg["user"],
                            password=cfg["password"], sender=cfg["from_addr"])
    return ConsoleProvider()


def mail_config_view(db: Session) -> dict:
    """给前端/HTTP 的视图：永不回显密码，只给 has_password + 组装是否完整。"""
    cfg = effective_mail_config(db)
    complete = bool(cfg["host"] and cfg["user"] and cfg["password"])
    return {
        "provider": cfg["provider"],
        "host": cfg["host"],
        "port": cfg["port"],
        "user": cfg["user"],
        "from_addr": cfg["from_addr"],
        "has_password": bool(cfg["password"]),
        "smtp_complete": complete,
    }


def save_mail_config(db: Session, patch: dict) -> dict:
    """部分更新邮件配置；password 缺省=保留 / 空串=清除 / 非空=替换（加密落库）。"""
    repo = DeploymentSettingsRepository(db)
    stored = dict(repo.get(MAIL_KEY) or {})

    provider = (patch.get("provider") or stored.get("provider") or "console").strip().lower()
    if provider not in MAIL_PROVIDERS:
        raise PlatformConfigError(f"未知邮件通道：{provider}")
    stored["provider"] = provider

    for field in ("host", "user", "from_addr"):
        if field in patch:
            stored[field] = (patch.get(field) or "").strip()
    if "port" in patch:
        try:
            stored["port"] = int(patch.get("port") or 465)
        except (TypeError, ValueError) as exc:
            raise PlatformConfigError("端口必须是数字") from exc
        if not (0 < stored["port"] < 65536):
            raise PlatformConfigError("端口范围 1-65535")

    # 个人邮箱（QQ/163/126）要求发件人地址=授权账号，否则服务器拒收（实测 501 Mail from
    # address must be same as authorization user），而验证码接口会把发送失败静默吞掉——
    # 必须在保存时就拦下，而不是等用户收不到码再查后端日志。
    if provider == "smtp" and stored.get("host") and stored.get("user") and stored.get("from_addr"):
        host_l = str(stored["host"]).lower()
        if any(p in host_l for p in ("smtp.qq.com", "smtp.163.com", "smtp.126.com")):
            from_domain = str(stored["from_addr"]).split("@")[-1].lower()
            user_domain = str(stored["user"]).split("@")[-1].lower()
            if from_domain != user_domain:
                raise PlatformConfigError(
                    f"QQ/163/126 邮箱的发件人地址必须与发信账号一致：请填 {stored['user']} 或留空"
                )

    if "password" in patch:
        value = (patch.get("password") or "").strip()
        stored["password_enc"] = secret_store.encrypt(value) if value else ""
    elif "password_enc" not in stored:
        stored["password_enc"] = ""  # 首次保存且未传密码：显式清零（此前 .env 的密码不再兜底外泄进库）

    repo.set(MAIL_KEY, stored)
    return mail_config_view(db)


def send_test_mail(db: Session, to: str) -> None:
    """发送测试邮件（admin 接口专用，允许如实回传错误——防枚举语义只属于验证码接口）。"""
    from agent_platform.infrastructure.mail.factory import (
        get_mail_provider as factory_resolve,
    )

    provider = factory_resolve(db)  # 与全站同一个入口（测试/日志/monkeypatch 都只认 factory）
    provider.send(to, "Agent Platform 测试邮件",
                  "这是一封测试邮件：收到它说明邮件通道配置成功。\n\n—— Agent Platform")


# ---------- 搜索源 ----------

def effective_search_config(db: Session) -> dict:
    """生效的搜索源配置：store 逐字段覆盖，缺字段回退 .env；Key 已解密。"""
    stored = DeploymentSettingsRepository(db).get(SEARCH_KEY) or {}
    return {
        "provider": (stored.get("provider") or settings.search_provider or "auto").strip().lower(),
        "api_key": secret_store.decrypt(stored.get("api_key_enc") or "") or settings.search_api_key,
    }


def search_config_view(db: Session) -> dict:
    cfg = effective_search_config(db)
    return {"provider": cfg["provider"], "has_api_key": bool(cfg["api_key"])}


def save_search_config(db: Session, patch: dict) -> dict:
    repo = DeploymentSettingsRepository(db)
    stored = dict(repo.get(SEARCH_KEY) or {})
    provider = (patch.get("provider") or stored.get("provider") or "auto").strip().lower()
    if provider not in SEARCH_PROVIDERS:
        raise PlatformConfigError(f"未知搜索源：{provider}")
    stored["provider"] = provider
    if "api_key" in patch:
        value = (patch.get("api_key") or "").strip()
        stored["api_key_enc"] = secret_store.encrypt(value) if value else ""
    elif "api_key_enc" not in stored:
        stored["api_key_enc"] = ""
    repo.set(SEARCH_KEY, stored)
    return search_config_view(db)
