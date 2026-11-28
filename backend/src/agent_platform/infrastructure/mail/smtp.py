"""SMTP 邮件提供方（v0.7）：smtplib 标准库 + SSL，QQ/163 邮箱授权码即可，零新依赖。

配置走 .env：SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / MAIL_FROM
（smtp.qq.com:465 或 smtp.163.com:465；密码填邮箱后台生成的授权码，不是登录密码）。
发件人必须与授权账号一致：QQ 实测对其它 From 拒收
（501 Mail from address must be same as authorization user），send() 对此前置报错。
个人规模（每天几十封）完全够用；到达率有要求时再在 factory 里加 DirectMail/Resend 分支。
"""
from __future__ import annotations

import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from agent_platform.config import settings


class SMTPProvider:
    channel = "smtp"

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        sender: str | None = None,
    ) -> None:
        self.host = host or settings.smtp_host
        self.port = int(port or settings.smtp_port or 465)
        self.user = user or settings.smtp_user
        self.password = password or settings.smtp_password
        self.sender = sender or settings.mail_from or self.user

    def send(self, to: str, subject: str, text: str) -> None:
        if not (self.host and self.user and self.password):
            raise RuntimeError("SMTP 未配置完整：需要 SMTP_HOST / SMTP_USER / SMTP_PASSWORD（.env）")
        host_l = (self.host or "").lower()
        if any(p in host_l for p in ("smtp.qq.com", "smtp.163.com", "smtp.126.com")) \
                and "@" in self.sender and self.sender.split("@")[-1].lower() \
                != self.user.split("@")[-1].lower():
            raise RuntimeError("发件人地址必须与授权账号一致（QQ/163/126 会拒收其它发件人）")
        message = MIMEText(text, "plain", "utf-8")
        message["Subject"] = Header(subject, "utf-8")
        message["From"] = formataddr((str(Header("Agent Platform", "utf-8")), self.sender))
        message["To"] = to
        # SSL 直连（465）：QQ/163 的标准端口；STARTTLS 场景未来再加分支
        with smtplib.SMTP_SSL(self.host, self.port, timeout=15) as client:
            client.login(self.user, self.password)
            client.sendmail(self.sender, [to], message.as_string())
