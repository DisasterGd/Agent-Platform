"""本地项目文件工具（v0.7.6）：Agent 在注册的真实目录内列目录/读文件/写文件。

安全边界（docs/design-local-projects.md §2/§4，本功能的命门）：
- root 由服务层经 functools.partial 注入，只来自数据库注册行（按 user_id 校验归属）——模型给不出 root；
- 所有路径经 safe_resolve（resolve() 吞掉 .. 与符号链接），越出一律拒绝并如实告知原因；
- 只提供 列目录/读文本/写文本 三件，**不提供删除/移动/命令执行**；写入自动创建父目录，
  单文件 2MB 上限，拒绝写进 .git。

与沙箱工具（write_file/create_zip，产物进 data/generated 登记）的分界：本组工具直接读写
真实项目目录，产物不进资料库、不产生 artifact 事件——磁盘就是事实来源。
"""
from __future__ import annotations

import json
from pathlib import Path

from agent_platform.infrastructure.filetypes import (
    content_type_for,
    human_size,
    is_readable_text,
)
from agent_platform.services.local_project_service import (
    MAX_TEXT_BYTES,
    MAX_TREE_ENTRIES,
    LocalProjectError,
    list_layer,
    safe_resolve,
)
from agent_platform.tools.registry import ToolResult

MAX_WRITE_BYTES = 2 * 1024 * 1024  # 单次写入上限（设计文档 §2）


def _err(message: str) -> ToolResult:
    return ToolResult(content=json.dumps({"ok": False, "error": message}, ensure_ascii=False))


LOCAL_LIST_DESCRIPTION = (
    "列出本地项目里某个目录的内容（条目含名称/类型/大小；node_modules、.git 等噪音目录不会出现）。"
    "路径用相对项目根的相对路径，根目录传 \".\" 或留空。用它在写文件前了解项目结构。"
)
LOCAL_LIST_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "相对项目根的目录路径，如 src/components；根目录传 \".\"",
        },
    },
    "required": ["path"],
}


def local_list_dir(path: str, root: Path) -> ToolResult:
    try:
        result = list_layer(root, path or ".")
    except LocalProjectError as exc:
        return _err(str(exc))
    note = f"（达到单层上限 {MAX_TREE_ENTRIES} 项，可能有遗漏）" if result["truncated"] else ""
    entries = [
        {"name": e["name"], "type": e["type"], **({"size": e["size"]} if e["type"] == "file" else {})}
        for e in result["entries"]
    ]
    return ToolResult(content=json.dumps(
        {"ok": True, "path": path or ".", "entries": entries, "note": note}, ensure_ascii=False,
    ))


LOCAL_READ_DESCRIPTION = (
    "读取本地项目里一个文本/代码文件的内容（相对项目根的路径）。二进制文件（图片/压缩包等）无法按文本读取，"
    "会如实告知类型与大小；超过 512KB 的文本文件本版本不支持读取。"
)
LOCAL_READ_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "相对项目根的文件路径，如 src/app.py",
        },
    },
    "required": ["path"],
}


def local_read_file(path: str, root: Path) -> ToolResult:
    try:
        target = safe_resolve(root, path)
    except LocalProjectError as exc:
        return _err(str(exc))
    if not target.exists():
        return _err("文件不存在")
    if target.is_dir():
        return _err("该路径是目录，请用 local_list_dir 列出")
    try:
        size = target.stat().st_size
    except OSError as exc:
        return _err(f"文件不可读：{exc}")
    name = target.name
    if not is_readable_text(name):
        return _err(f"二进制文件（{content_type_for(name)}，{human_size(size)}），无法按文本读取")
    if size > MAX_TEXT_BYTES:
        return _err(f"文件过大（{human_size(size)}），本版本不支持读取")
    try:
        text = target.read_bytes().decode("utf-8", errors="replace")
    except OSError as exc:
        return _err(f"文件不可读：{exc}")
    return ToolResult(content=json.dumps(
        {"ok": True, "path": path, "size": size, "content": text}, ensure_ascii=False,
    ))


LOCAL_WRITE_DESCRIPTION = (
    "在本地项目里创建或覆盖一个文本/代码文件（相对项目根的路径；父目录不存在会自动创建）。"
    "content 是文件完整内容，原样写入，不要加 Markdown 代码围栏。单文件上限 2MB；"
    "写入成功即落盘到用户真实目录，用户可直接用本机工具查看与修改。"
)
LOCAL_WRITE_PARAMETERS: dict = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "相对项目根的文件路径，如 src/utils/helpers.py",
        },
        "content": {
            "type": "string",
            "description": "文件完整内容（原样写入，不要 Markdown 围栏、不要解释）",
        },
    },
    "required": ["path", "content"],
}


def local_write_file(path: str, content: str, root: Path) -> ToolResult:
    try:
        target = safe_resolve(root, path)
        anchor = root.resolve()
    except LocalProjectError as exc:
        return _err(str(exc))
    if target == anchor:
        return _err("不能把项目根目录本身当作文件写入")
    rel_parts = target.relative_to(anchor).parts
    if any(part == ".git" for part in rel_parts[:-1]) or rel_parts[0] == ".git":
        return _err("不允许写进 .git 目录")
    if target.is_dir():
        return _err("目标路径已是目录，请换一个文件名")
    data = (content or "").encode("utf-8")
    if len(data) > MAX_WRITE_BYTES:
        return _err(f"内容过大（{human_size(len(data))}），单次写入上限 2MB")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except OSError as exc:
        return _err(f"写入失败：{exc}")
    lines = len(content.splitlines()) if content else 0
    return ToolResult(content=json.dumps(
        {
            "ok": True,
            "path": path,
            "size_label": human_size(len(data)),
            "lines": lines,
            "note": "已写入磁盘真实文件",
        },
        ensure_ascii=False,
    ))
