"""v0.5 文本与压缩包生成：供 write_file / create_zip 工具调用。

与 documents.DocumentGenerator 的分工：
- 文档格式（md / docx / pdf）由 Markdown 渲染，标题决定文件名；
- 文本、代码、配置**原样写出**，文件名由模型给出——程序员把用途写进文件名与路径
  （`src/app/main.py`、`tests/test_login.py`），这一层只负责清洗与把关。

安全边界（呼应开发指南“不信任模型给的路径”）：
- 后缀必须在文本白名单内，二进制（.exe/.png/.zip）拒绝由本模块写出；
- 路径清洗：拒绝绝对路径与 `..` 上跳，Windows 非法字符替换；
- 体积与数量上限：单文件 4MB、压缩包条目 300 个 / 总 64MB，超限报错让模型拆分。
"""
from __future__ import annotations

import re
import zipfile
from io import BytesIO

from agent_platform.infrastructure import filetypes as ft

MAX_TEXT_BYTES = 4 * 1024 * 1024
MAX_ZIP_ENTRIES = 300
MAX_ZIP_BYTES = 64 * 1024 * 1024

_WINDOWS_RESERVED = re.compile(r"^(con|prn|aux|nul|com\d+|lpt\d+)$", re.IGNORECASE)


def _safe_filename(name: str, *, require_suffix: bool = True) -> str:
    """清洗成单个文件名（去路径、去非法字符），保留大小写。"""
    base = (name or "").replace("\\", "/").strip().rsplit("/", 1)[-1]
    base = re.sub(r'[<>:"|?*\x00-\x1f]+', "_", base).strip().strip(". ")
    if not base:
        raise ValueError("文件名为空")
    stem, dot, ext = base.partition(".")
    if _WINDOWS_RESERVED.match(stem or base):
        base = f"_{base}"
    if require_suffix and not dot and base.lower() not in ft.SPECIAL_NAMES:
        raise ValueError(f"文件名 {base} 没有扩展名，请带上后缀（如 {base}.py / {base}.md）")
    if len(base) > 160:
        keep = base[:120]
        base = f"{keep}{dot}{ext}"[:160]
    return base


def build_text_file(filename: str, content: str) -> tuple[str, str, bytes]:
    """按模型给的文件名原样写出文本文件，返回 (filename, content_type, bytes)。"""
    name = _safe_filename(filename)
    if not ft.is_writable_text(name):
        raise ValueError(
            f"不支持写出 .{ft.suffix_of(name) or name} 这类文件；只放行文本/代码/配置。{ft.WRITABLE_HINT}"
        )
    data = (content or "").encode("utf-8")
    if len(data) > MAX_TEXT_BYTES:
        raise ValueError(f"内容过大（{ft.human_size(len(data))} > {ft.human_size(MAX_TEXT_BYTES)}），请拆成多个文件")
    return name, ft.content_type_for(name), data


def build_zip(name: str, files: list[dict], extras: list[tuple[str, bytes]] | None = None) -> tuple[str, str, bytes]:
    """把多个文本文件（+ 已生成的文件内容 extras）打成 zip。

    files: [{"path": "src/main.py", "content": "..."}]，path 允许带目录（zip 内层级）。
    extras: [(arcname, bytes)]，由调用方从存储层读出（例如把先前生成的文件并入包）。
    """
    entries: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    rejected: list[str] = []

    for item in files or []:
        path = ft.normalize_path(str(item.get("path", "")), default_name="file.txt")
        content = str(item.get("content", "") or "")
        if not ft.is_writable_text(path):
            rejected.append(path)
            continue
        data = content.encode("utf-8")
        if len(data) > MAX_TEXT_BYTES:
            rejected.append(f"{path}（{ft.human_size(len(data))} 超限）")
            continue
        entries.append((path, data))
        seen.add(path)

    for path, data in extras or []:
        path = ft.normalize_path(path, default_name="file.bin")
        if path in seen:                       # 同名不覆盖：加序号
            stem, dot, ext = path.rpartition(".") if "." in path else (path, "", "")
            n = 2
            while f"{stem} ({n}){dot}{ext}" in seen:
                n += 1
            path = f"{stem} ({n}){dot}{ext}"
        entries.append((path, data))
        seen.add(path)

    if rejected:
        raise ValueError(
            "以下条目不是可写出的文本文件，未打包：" + "、".join(rejected[:8])
            + f"。{ft.WRITABLE_HINT}"
        )
    if not entries:
        raise ValueError("压缩包内容为空：files 至少要有 {path, content} 一项")
    if len(entries) > MAX_ZIP_ENTRIES:
        raise ValueError(f"条目过多（{len(entries)} > {MAX_ZIP_ENTRIES}），请分批打包")

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path, data in entries:
            if sum(i.file_size for i in zf.infolist()) + len(data) > MAX_ZIP_BYTES:
                raise ValueError(f"压缩包超过 {ft.human_size(MAX_ZIP_BYTES)}，请分批打包")
            zf.writestr(path, data)
    payload = buf.getvalue()
    if len(payload) > MAX_ZIP_BYTES:
        raise ValueError(f"压缩包超过 {ft.human_size(MAX_ZIP_BYTES)}，请分批打包")

    filename = _safe_filename(name if name.strip() else "project", require_suffix=False)
    if not filename.lower().endswith((".zip",)):
        filename = f"{filename}.zip"
    return filename, "application/zip", payload


def list_zip_entries(data: bytes) -> list[dict]:
    """读压缩包目录（资料库预览用）：名称/大小/是否目录，按层级排序。"""
    out: list[dict] = []
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            for info in zf.infolist():
                out.append({
                    "path": info.filename,
                    "size": info.file_size,
                    "is_dir": info.is_dir(),
                })
    except (zipfile.BadZipFile, OSError):
        return []
    out.sort(key=lambda e: e["path"].lower())
    return out


def zip_contains_text(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            return bool(zf.infolist())
    except (zipfile.BadZipFile, OSError):
        return False
