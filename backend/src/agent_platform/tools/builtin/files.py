"""文件生成工具：把 Markdown 内容导出为 md / docx / pdf。"""
from __future__ import annotations

import json

from agent_platform.infrastructure.generation.documents import DocumentGenerator
from agent_platform.infrastructure.storage.local import get_storage
from agent_platform.tools.registry import ToolResult

GENERATE_FILE_DESCRIPTION = (
    "把内容导出成文件。当用户要求生成文档、报告、说明、总结等需要下载的文件时调用。"
    "format 支持 md（Markdown）、docx（Word）、pdf（PDF）。content 用 Markdown 编写。"
)
GENERATE_FILE_PARAMETERS = {
    "type": "object",
    "properties": {
        "format": {
            "type": "string",
            "enum": ["md", "docx", "pdf"],
            "description": "目标文件格式",
        },
        "title": {"type": "string", "description": "文档标题（也会作为文件名）"},
        "content": {"type": "string", "description": "文档正文，Markdown 格式"},
    },
    "required": ["format", "title", "content"],
}


def generate_file(format: str, title: str, content: str) -> ToolResult:
    filename, content_type, data = DocumentGenerator().generate(format, title, content)
    stored = get_storage().save("generated", filename, data, content_type)
    # 显示名 = 磁盘真实名 = 下载链接名（重名时带 “ (2)” 序号），方便直接在 data/generated 里翻阅
    artifact = {
        "filename": stored.stored_name,
        "stored_name": stored.stored_name,
        "url": stored.url,
        "format": format,
        "content_type": content_type,
    }
    return ToolResult(
        content=json.dumps(
            {"ok": True, "filename": stored.stored_name, "url": stored.url, "format": format},
            ensure_ascii=False,
        ),
        artifacts=[artifact],
    )
