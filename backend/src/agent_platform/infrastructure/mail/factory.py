"""邮件提供方工厂（v0.7）：按 .env 的 MAIL_PROVIDER 组装（console | smtp）。"""
from __future__ import annotations

from functools import lru_cache

from agent_platform.config import settings
from agent_platform.infrastructure.mail.base import MailProvider
from agent_platform.infrastructure.mail.console import ConsoleProvider
from agent_platform.infrastructure.mail.smtp import SMTPProvider


@lru_cache
def get_mail_provider() -> MailProvider:
    provider = (settings.mail_provider or "console").strip().lower()
    if provider == "smtp":
        return SMTPProvider()
    return ConsoleProvider()  # 默认与未知值都落控制台，绝不因配置笔误炸掉登录
