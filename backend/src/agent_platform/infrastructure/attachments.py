"""附件内容提取：文本/PDF/DOCX 提取正文，图片转 data URI 供视觉模型识图。"""
from __future__ import annotations

import base64
from io import BytesIO

from agent_platform.infrastructure.storage.local import get_storage

_TEXT_SUFFIXES = (".txt", ".md", ".csv", ".json", ".xml", ".log", ".yml", ".yaml", ".py", ".ts", ".js")
_TEXT_TYPES = {"text/plain", "text/markdown", "text/csv", "application/json", "application/xml"}


def _read_bytes(category: str, stored_name: str) -> bytes | None:
    path = get_storage().resolve(category, stored_name)
    if path is None:
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def extract_text(category: str, stored_name: str, content_type: str) -> str | None:
    """提取文本附件正文；无法识别（如图片）返回 None。"""
    data = _read_bytes(category, stored_name)
    if data is None:
        return None
    name = (stored_name or "").lower()
    ct = (content_type or "").lower()
    if ct in _TEXT_TYPES or name.endswith(_TEXT_SUFFIXES):
        return _decode(data)
    if name.endswith(".pdf"):
        return _extract_pdf(data)
    if name.endswith(".docx"):
        return _extract_docx(data)
    return None


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


def image_to_data_uri(category: str, stored_name: str, content_type: str) -> str | None:
    """把图片读成 base64 data URI，供视觉模型识图。"""
    data = _read_bytes(category, stored_name)
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
