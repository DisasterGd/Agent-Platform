"""本地项目用例（v0.7.4）：真实目录的注册与浏览，伪编辑器与本地项目工具共用的路径安全层。

安全边界（docs/design-local-projects.md §2，本功能的命门）：
- root 只来自数据库注册行（按 user_id 校验归属），模型/前端给的路径永远不当 root；
- safe_resolve 用 resolve() 吞掉 `..` 与符号链接，越出项目根一律拒绝（Windows 也不例外）；
- 忽略清单过滤 node_modules/.git 等噪音目录；目录条目有单层上限。
明确不做：删除/移动文件、命令执行（防越界是第一优先级）。
"""
from __future__ import annotations

import string
from pathlib import Path

# 树与目录浏览共用的噪音目录（.gitignore 解析留后续，v0.7.4 固定清单）
IGNORED_NAMES = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".idea", ".vs"}
MAX_BROWSE_ENTRIES = 500


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
