"""邮件提供方工厂（v0.7 起；v0.8.0 改部署级配置实时解析）。

入口保持 get_mail_provider(db)：传 Session 时走 deployment_settings 的邮件配置
（界面改完即生效，无需重启）；不传 db（防御/直调）按 .env 组装（旧行为兜底）。
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from agent_platform.config import settings
from agent_platform.infrastructure.mail.base import MailProvider
from agent_platform.infrastructure.mail.console import ConsoleProvider
from agent_platform.infrastructure.mail.smtp import SMTPProvider


def get_mail_provider(db: Session | None = None) -> MailProvider:
    if db is not None:
        from agent_platform.services.platform_settings import (
            get_mail_provider as resolve_from_store,
        )

        return resolve_from_store(db)
    # 无 db 的兜底：按 .env 组装（本地直调/脚本场景）
    provider = (settings.mail_provider or "console").strip().lower()
    if provider == "smtp":
        return SMTPProvider()
    return ConsoleProvider()  # 默认与未知值都落控制台，绝不因配置笔误炸掉登录
