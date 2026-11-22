"""write_file 工具（v0.5）：把文本/代码/配置按模型指定的文件名原样写出。

与 generate_file 的分界：generate_file 负责“文档”（Markdown → md/docx/pdf），
write_file 负责“文件”——文件名与后缀就是用途声明，内容原样落盘不做任何渲染。
"""
from __future__ import annotations

import json

from agent_platform.infrastructure.filetypes import (
    WRITABLE_HINT,
    classify_kind,
    human_size,
)
from agent_platform.infrastructure.generation.textfiles import build_text_file
from agent_platform.infrastructure.storage.local import get_storage
from agent_platform.tools.registry import ToolResult

WRITE_FILE_DESCRIPTION = (
    "按指定文件名原样写出一个文本文件（不做任何格式化），用于生成代码、配置、脚本、"
    "网页、数据文件等交付物。文件名与扩展名由你决定并决定用途，例如 main.py、test_login.py、"
    "docker-compose.yml、index.html、README.md（保存时只取文件名部分，目录层级请用 create_zip 表达）。"
    "要生成 Word/PDF 文档时用 generate_file；要一次交付多个文件时先逐个 write_file，"
    f"再用 create_zip 打包。{WRITABLE_HINT}"
)
WRITE_FILE_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "filename": {
            "type": "string",
            "description": "文件名，必须包含扩展名（如 main.py）；只取文件名部分，不含目录",
        },
        "content": {
            "type": "string",
            "description": "文件完整内容，原样写入（不要加 Markdown 代码围栏或解释文字）",
        },
    },
    "required": ["filename", "content"],
}


def write_file(filename: str, content: str) -> ToolResult:
    try:
        name, mime, data = build_text_file(filename, content)
    except ValueError as exc:
        return ToolResult(content=json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
    stored = get_storage().save("generated", name, data, mime)
    artifact = {
        "filename": stored.stored_name,
        "stored_name": stored.stored_name,
        "url": stored.url,
        "format": stored.stored_name.rpartition(".")[2] or "txt",
        "content_type": stored.content_type,
        "category": stored.category,
        "size": stored.size,
        "kind": classify_kind(name, mime),
    }
    return ToolResult(
        content=json.dumps(
            {
                "ok": True,
                "filename": stored.stored_name,
                "url": stored.url,
                "size_label": human_size(stored.size),
                "content_type": stored.content_type,
            },
            ensure_ascii=False,
        ),
        artifacts=[artifact],
    )
