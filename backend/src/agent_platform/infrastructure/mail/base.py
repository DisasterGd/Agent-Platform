"""邮件发送抽象（v0.7）：与 SearchProvider 同款协议模式，按 .env 的 MAIL_PROVIDER 组装。"""
from __future__ import annotations

from typing import Protocol


class MailProvider(Protocol):
    @property
    def channel(self) -> str:
        """通道标识（如 "console" / "smtp"）；/auth/request-code 响应如实回给前端做提示，不含敏感信息。"""
        ...

    def send(self, to: str, subject: str, text: str) -> None:
        """发送一封纯文本邮件；失败抛异常（调用方决定如何呈现，发码接口不区分邮箱存在性——防枚举）。"""
        ...
