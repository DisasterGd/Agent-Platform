"""create_zip 工具（v0.5）：把多个文件打成一个可下载的 zip 压缩包。

两种来源可混用：
- files：本回合直接给出的 {path, content}（适合“一次成型”的小项目）；
- from_files：先前 write_file / generate_file 产出过的文件（url 或文件名），
  适合“先逐个写、再整体打包”，避免把内容重复输出一遍。
"""
from __future__ import annotations

import json

from agent_platform.infrastructure import filetypes as ft
from agent_platform.infrastructure.attachments import parse_file_url
from agent_platform.infrastructure.generation.textfiles import (
    build_zip,
    list_zip_entries,
)
from agent_platform.infrastructure.storage.local import get_storage
from agent_platform.tools.registry import ToolResult

MAX_INLINE_FILES = 60
MAX_REFERENCES = 120

CREATE_ZIP_DESCRIPTION = (
    "把多个文件打包成一个 zip 压缩包供用户下载。用于交付“一整个项目/一套代码”这类多文件成果。"
    "两种内容来源可以混用：files 直接内联给出 [{path, content}]（path 可含目录，如 src/app/main.py）；"
    "from_files 引用本轮对话中先前生成过的文件（填它们的 url 或文件名），这样不必重复输出内容。"
    "典型用法：先逐个 write_file 写出各源文件，再用 create_zip 并附 from_files 引用它们。"
)
CREATE_ZIP_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "filename": {"type": "string", "description": "压缩包文件名，如 todo-app.zip（省略 .zip 会自动补上）"},
        "files": {
            "type": "array",
            "description": "要打包的文件（内联内容）",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "包内相对路径，含扩展名，如 src/main.py"},
                    "content": {"type": "string", "description": "该文件的完整内容"},
                },
                "required": ["path", "content"],
            },
            "maxItems": MAX_INLINE_FILES,
        },
        "from_files": {
            "type": "array",
            "description": "引用已生成过的文件：填 write_file/generate_file 返回的 url 或文件名",
            "items": {"type": "string"},
            "maxItems": MAX_REFERENCES,
        },
    },
    "required": ["filename"],
}


def _resolve_reference(ref: str) -> tuple[str, bytes] | None:
    """把模型给的 url 或文件名解析成 (包内路径, 字节内容)。"""
    storage = get_storage()
    parsed = parse_file_url(ref)
    if parsed is not None:
        category, stored_name = parsed
        data = storage.read_bytes(category, stored_name)
        return (stored_name, data) if data is not None else None
    name = (ref or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    if not name:
        return None
    for category in ("generated", "uploads"):
        data = storage.read_bytes(category, name)
        if data is not None:
            return name, data
    return None


def create_zip(
    filename: str, files: list[dict] | None = None, from_files: list[str] | None = None
) -> ToolResult:
    files = [f for f in (files or []) if isinstance(f, dict)][:MAX_INLINE_FILES]
    refs = [str(r) for r in (from_files or []) if str(r).strip()][:MAX_REFERENCES]

    extras: list[tuple[str, bytes]] = []
    missing: list[str] = []
    for ref in refs:
        found = _resolve_reference(ref)
        if found is None:
            missing.append(ref)
        else:
            extras.append(found)

    if missing and not files and not extras:
        return ToolResult(
            content=json.dumps(
                {
                    "ok": False,
                    "error": "没有找到任何可打包的文件",
                    "missing": missing[:10],
                    "hint": "from_files 要用先前工具返回的 url 或文件名；也可以直接用 files 内联内容",
                },
                ensure_ascii=False,
            )
        )
    try:
        name, mime, data = build_zip(filename, files, extras)
    except ValueError as exc:
        payload: dict = {"ok": False, "error": str(exc)}
        if missing:
            payload["missing"] = missing[:10]
        return ToolResult(content=json.dumps(payload, ensure_ascii=False))

    stored = get_storage().save("generated", name, data, mime)
    entries = [e["path"] for e in list_zip_entries(data)]
    artifact = {
        "filename": stored.stored_name,
        "stored_name": stored.stored_name,
        "url": stored.url,
        "format": "zip",
        "content_type": stored.content_type,
        "category": stored.category,
        "size": stored.size,
        "kind": ft.KIND_ARCHIVE,
    }
    result: dict = {
        "ok": True,
        "filename": stored.stored_name,
        "url": stored.url,
        "entry_count": len(entries),
        "entries": entries[:80],
        "size_label": ft.human_size(stored.size),
    }
    if missing:
        result["skipped"] = missing[:10]
        result["note"] = "以上引用未找到对应文件，已跳过（其余照常打包）"
    return ToolResult(content=json.dumps(result, ensure_ascii=False), artifacts=[artifact])
