"""控制台邮件提供方（v0.7）：把邮件内容直接打到日志，本地调试 cloud 模式用。

AUTH_MODE=cloud 且 MAIL_PROVIDER=console（默认）时，验证码只出现在后端控制台——
不出网也能走完注册/登录全流程。
"""
from __future__ import annotations

import logging

logger = logging.getLogger("agent_platform.mail")


class ConsoleProvider:
    def send(self, to: str, subject: str, text: str) -> None:
        logger.warning("[console-mail] to=%s subject=%s\n%s", to, subject, text)
