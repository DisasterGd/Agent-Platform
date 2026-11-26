"""邮件发送抽象（v0.7）：与 SearchProvider 同款协议模式，按 .env 的 MAIL_PROVIDER 组装。"""
from __future__ import annotations

from typing import Protocol


class MailProvider(Protocol):
    def send(self, to: str, subject: str, text: str) -> None:
        """发送一封纯文本邮件；失败抛异常（调用方决定如何呈现，验证码接口统一 204 防枚举）。"""
        ...
