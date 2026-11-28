"""本地项目用例（v0.7.4）：真实目录的注册与浏览，伪编辑器与本地项目工具共用的路径安全层。

安全边界（docs/design-local-projects.md §2，本功能的命门）：
- root 只来自数据库注册行（按 user_id 校验归属），模型/前端给的路径永远不当 root；
- safe_resolve 用 resolve() 吞掉 `..` 与符号链接，越出项目根一律拒绝（Windows 也不例外）；
- 忽略清单过滤 node_modules/.git 等噪音目录；目录条目有单层上限。
明确不做：删除/移动文件、命令执行（防越界是第一优先级）。
"""
from __future__ import annotations

import base64
import string
import threading
from pathlib import Path

from agent_platform.infrastructure.filetypes import (
    IMAGE_SUFFIXES,
    content_type_for,
    is_readable_text,
    suffix_of,
)

# 树与目录浏览共用的噪音目录（.gitignore 解析留后续，v0.7.4 固定清单）
IGNORED_NAMES = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".idea", ".vs"}
MAX_BROWSE_ENTRIES = 500
# v0.7.5 伪编辑器硬上限（设计文档 §2）
MAX_TREE_ENTRIES = 500
MAX_TEXT_BYTES = 512 * 1024          # 文本预览：超出只回元信息
MAX_IMAGE_BYTES = 10 * 1024 * 1024   # 图片预览：超出按二进制只给元信息


class LocalProjectError(Exception):
    """带用户可读信息的本地项目错误（路由层转 400/404）。"""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def normalize_root(raw: str) -> Path:
    """注册时的 root 校验：存在、是目录、返回解析后的绝对路径（存库即此形态）。"""
    text = (raw or "").strip().strip('"')
    if not text:
        raise LocalProjectError("请填写项目目录路径")
    path = Path(text).expanduser()
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise LocalProjectError(f"路径无法解析：{exc}") from exc
    if not resolved.exists():
        raise LocalProjectError("目录不存在，请检查路径")
    if not resolved.is_dir():
        raise LocalProjectError("该路径不是目录（本地项目指向一个真实文件夹）")
    return resolved


def safe_resolve(root: Path, rel: str) -> Path:
    """把相对（或 root 内的绝对）路径解析到 root 之下；越界/无效一律抛错。

    resolve() 展开所有 `..` 与符号链接后再做前缀判定，`is_relative_to` 保证 target 严格落在
    root（含 root 本身）之内——这是防路径穿越的唯一真源，工具与路由都必须经它。
    """
    anchor = root.resolve()
    text = (rel or ".").strip()
    if not text:
        text = "."
    candidate = Path(text)
    try:
        target = (candidate if candidate.is_absolute() else anchor / candidate).resolve()
    except OSError as exc:
        raise LocalProjectError(f"路径无法解析：{exc}") from exc
    if not (target == anchor or target.is_relative_to(anchor)):
        raise LocalProjectError("路径越出项目根目录")
    return target


def list_drives() -> list[str]:
    """选目录弹窗起点：Windows 盘符（存在的才返回）；非 Windows 返回根目录。"""
    import sys

    if sys.platform != "win32":
        return ["/"]
    found: list[str] = []
    for letter in string.ascii_uppercase:
        drive = Path(f"{letter}:\\")
        try:
            if drive.exists():
                found.append(f"{letter}:\\")
        except OSError:
            continue
    return found


def browse(path: str) -> dict:
    """逐层选目录：返回该目录下的子目录（忽略清单生效、排序、限量）。"""
    if not (path or "").strip():
        raise LocalProjectError("路径不能为空")
    try:
        current = Path(path.strip().strip('"')).expanduser().resolve()
    except OSError as exc:
        raise LocalProjectError(f"路径无法解析：{exc}") from exc
    if not current.exists() or not current.is_dir():
        raise LocalProjectError("目录不存在或不可读")
    dirs: list[str] = []
    try:
        for entry in current.iterdir():
            if not entry.is_dir() or entry.name in IGNORED_NAMES:
                continue
            dirs.append(entry.name)
            if len(dirs) >= MAX_BROWSE_ENTRIES:
                break
    except OSError as exc:
        raise LocalProjectError(f"目录不可读：{exc}") from exc
    parent = str(current.parent) if current.parent != current else ""
    return {"path": str(current), "parent": parent, "dirs": sorted(dirs, key=str.lower)}


# v0.8.2 原生目录选择：同一时刻只允许一个对话框（对话框是模态的，用户不选完不返回）
_pick_lock = threading.Lock()


def pick_directory() -> str | None:
    """弹系统原生「选择目录」对话框（Windows 文件管理器外观），返回选中的绝对路径；取消返回 None。

    v0.8.2：替代前端自绘的逐层目录树（FolderPickerModal）——本机后端就在用户机器上，
    直接用 tkinter 的 askdirectory 弹真·文件管理器窗口，体验与上传附件一致。
    tkinter 每线程一个 Tk 实例：这里在独立线程跑（路由层 asyncio.to_thread），互不干扰；
    置顶属性防对话框被浏览器窗口挡住（用户以为按钮没反应）。
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise LocalProjectError("本机 Python 缺少 tkinter，无法弹出目录选择窗口", status_code=503) from exc

    if not _pick_lock.acquire(blocking=False):
        raise LocalProjectError("已有一个目录选择窗口未关闭，请先完成或取消它", status_code=409)
    try:
        root = tk.Tk()
        try:
            root.withdraw()  # 不显示主窗口，只要对话框
            root.attributes("-topmost", True)
            path = filedialog.askdirectory(parent=root, title="选择要注册为本地项目的目录")
        finally:
            root.destroy()
        return path or None
    finally:
        _pick_lock.release()


def list_layer(root: Path, rel: str = ".") -> dict:
    """伪编辑器树的单层懒加载：目录在前、文件按名排，噪音目录不出现，单层限量防大仓库卡死。"""
    directory = safe_resolve(root, rel)
    if not directory.is_dir():
        raise LocalProjectError("该路径不是目录")
    entries: list[dict] = []
    truncated = False
    try:
        for entry in directory.iterdir():
            if entry.name in IGNORED_NAMES:
                continue
            if len(entries) >= MAX_TREE_ENTRIES:
                truncated = True
                break
            try:
                if entry.is_dir():
                    entries.append({"name": entry.name, "type": "dir", "size": None})
                elif entry.is_file():
                    entries.append({"name": entry.name, "type": "file", "size": entry.stat().st_size})
            except OSError:
                continue  # 竞态删除/权限拒绝的条目跳过，不炸整层
    except OSError as exc:
        raise LocalProjectError(f"目录不可读：{exc}") from exc
    entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
    return {"path": str(directory), "entries": entries, "truncated": truncated}


def read_file(root: Path, rel: str) -> dict:
    """伪编辑器文件内容：text（≤512KB 解码预览，超出只回元信息）/ image（≤10MB data URI）/ binary（只回元信息）。

    类型判定只走 infrastructure/filetypes（IMAGE_SUFFIXES + is_readable_text），不在本处另写后缀表；
    svg 虽是文本但按 image data URI 渲染（避免把 SVG 当 HTML 注入）。
    """
    target = safe_resolve(root, rel)
    if not target.exists():
        raise LocalProjectError("文件不存在", status_code=404)
    if target.is_dir():
        raise LocalProjectError("该路径是目录，请先展开查看")
    name = target.name
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise LocalProjectError(f"文件不可读：{exc}") from exc

    if suffix_of(name) in IMAGE_SUFFIXES:
        mime = content_type_for(name)
        if size <= MAX_IMAGE_BYTES:
            data = base64.b64encode(target.read_bytes()).decode("ascii")
            return {"kind": "image", "mime": mime, "size": size,
                    "content": f"data:{mime};base64,{data}", "truncated": False}
        return {"kind": "binary", "mime": mime, "size": size, "content": None, "truncated": False}

    if is_readable_text(name):
        if size <= MAX_TEXT_BYTES:
            raw = target.read_bytes()
            return {"kind": "text", "mime": content_type_for(name), "size": size,
                    "content": raw.decode("utf-8", errors="replace"), "truncated": False}
        return {"kind": "text", "mime": content_type_for(name), "size": size,
                "content": None, "truncated": True}

    return {"kind": "binary", "mime": content_type_for(name), "size": size,
            "content": None, "truncated": False}
