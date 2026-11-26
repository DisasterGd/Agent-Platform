"""附件内容提取：文本/代码/配置直接读正文，PDF/DOCX 解析，图片转 data URI 供视觉模型识图。

文本判定用 infrastructure/filetypes 的统一口径：后缀在白名单里，或后缀未知但内容嗅探像文本
（程序员上传的文件名五花八门：Makefile、.env、requirements.txt、无后缀的脚本）。
正文按长度截断，避免一个巨型日志文件挤掉整个上下文窗口。
"""
from __future__ import annotations

import base64
from io import BytesIO

from agent_platform.infrastructure import filetypes as ft
from agent_platform.infrastructure.storage.local import get_storage

MAX_EXTRACT_BYTES = 512 * 1024  # 单个附件最多读 512KB 正文
TRUNCATED_NOTE = "\n…（正文过长，已截断）"


def _read_bytes(category: str, stored_name: str, limit: int | None = None, user_id: int | None = None) -> bytes | None:
    return get_storage().read_bytes(category, stored_name, limit, user_id=user_id)


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def extract_text(
    category: str, stored_name: str, content_type: str, user_id: int | None = None
) -> str | None:
    """提取文本附件正文；无法识别（如图片、压缩包）返回 None。user_id 限定读取该用户目录。"""
    name = (stored_name or "").lower()
    ct = (content_type or "").lower()
    if name.endswith(".pdf"):
        data = _read_bytes(category, stored_name, user_id=user_id)
        return _extract_pdf(data) if data else None
    if name.endswith(".docx"):
        data = _read_bytes(category, stored_name, user_id=user_id)
        return _extract_docx(data) if data else None
    data = _read_bytes(category, stored_name, user_id=user_id)
    if data is None:
        return None
    if not ft.is_readable_text(name, data, ct):
        return None
    text = _decode(data)
    if len(text) > MAX_EXTRACT_BYTES:
        text = text[:MAX_EXTRACT_BYTES] + TRUNCATED_NOTE
    return text or None


def _extract_pdf(data: bytes) -> str | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    reader = PdfReader(BytesIO(data))
    parts = [page.extract_text() or "" for page in reader.pages[:20]]
    text = "\n".join(parts).strip()
    return text or None


def _extract_docx(data: bytes) -> str | None:
    try:
        from docx import Document
    except ImportError:
        return None
    doc = Document(BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs).strip()
    return text or None


def image_to_data_uri(
    category: str, stored_name: str, content_type: str, user_id: int | None = None
) -> str | None:
    """把图片读成 base64 data URI，供视觉模型识图。"""
    data = _read_bytes(category, stored_name, user_id=user_id)
    if data is None:
        return None
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{content_type or 'application/octet-stream'};base64,{b64}"


def parse_file_url(url: str) -> tuple[str, str] | None:
    """把 /api/files/{category}/{stored_name} 解析为 (category, stored_name)。"""
    path = (url or "").split("?", 1)[0].strip("/")
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 3 and parts[-3] == "files":
        return parts[-2], parts[-1]
    return None
