"""本地文件存储：上传文件与 Agent 生成文件，未来可替换为对象存储。

落盘使用**可读文件名**（与 artifact 显示名、下载链接一致），便于直接翻阅 data 目录：
- 清洗 Windows 非法字符与控制符，去掉路径部分；
- 同名不覆盖，自动追加序号（报告.md → 报告 (2).md）；
- 历史 uuid 命名的文件不受影响，旧链接照常可用。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from agent_platform.config import settings

# Windows 下文件名非法字符 + 控制符
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
# Windows 保留设备名（不区分大小写，含带扩展名形式）
_RESERVED = re.compile(r"^(con|prn|aux|nul|com\d+|lpt\d+)$", re.IGNORECASE)
_MAX_STEM = 100
_MAX_COLLISION = 999


def _sanitize(filename: str) -> str:
    """把任意原始文件名清洗成磁盘可用的可读名。"""
    name = Path(filename).name.strip() or "file"
    stem, ext = Path(name).stem, Path(name).suffix
    stem = _INVALID_CHARS.sub("_", stem).strip().rstrip(". ")[:_MAX_STEM]
    if not stem:
        stem = "file"
    if _RESERVED.match(stem):
        stem = f"_{stem}"
    ext = _INVALID_CHARS.sub("_", ext)[:16]
    return f"{stem}{ext}"


def _unique_path(directory: Path, name: str) -> Path:
    """同名不覆盖：报告.md → 报告 (2).md → 报告 (3).md …"""
    target = directory / name
    if not target.exists():
        return target
    stem, ext = Path(name).stem, Path(name).suffix
    for n in range(2, _MAX_COLLISION + 1):
        target = directory / f"{stem} ({n}){ext}"
        if not target.exists():
            return target
    # 极端情况（999 个重名）退回唯一串，保证可写
    import uuid

    return directory / f"{stem}-{uuid.uuid4().hex[:8]}{ext}"


@dataclass
class StoredFile:
    filename: str       # 原始文件名（清洗后）
    stored_name: str    # 磁盘上的真实文件名（可读；重名自动加序号）
    category: str       # "uploads" | "generated"
    content_type: str
    size: int

    @property
    def url(self) -> str:
        # 由 apps/api/routes/files.py 提供下载，前端同源访问，dev 下走 vite 的 /api 代理。
        return f"/api/files/{self.category}/{self.stored_name}"

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "url": self.url,
            "content_type": self.content_type,
            "size": self.size,
        }


class LocalStorage:
    def __init__(self, base_dir: Path) -> None:
        self.base = base_dir
        self.uploads = base_dir / "uploads"
        self.generated = base_dir / "generated"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.generated.mkdir(parents=True, exist_ok=True)

    def _dir(self, category: str) -> Path:
        return self.uploads if category == "uploads" else self.generated

    def save(self, category: str, filename: str, content: bytes, content_type: str) -> StoredFile:
        safe_name = _sanitize(filename)
        target = _unique_path(self._dir(category), safe_name)
        target.write_bytes(content)
        return StoredFile(
            filename=safe_name,
            stored_name=target.name,  # 可读名；重名时带 “ (2)” 之类序号
            category=category,
            content_type=content_type,
            size=len(content),
        )

    def resolve(self, category: str, stored_name: str) -> Path | None:
        # 只允许访问已知目录，且必须是纯文件名（拒绝路径穿越；“a..b.md”这类合法名不误伤）
        if stored_name in ("", ".", "..") or Path(stored_name).name != stored_name:
            return None
        target = self._dir(category) / stored_name
        return target if target.is_file() else None


_storage: LocalStorage | None = None


def get_storage() -> LocalStorage:
    global _storage
    if _storage is None:
        _storage = LocalStorage(Path(settings.storage_dir))
    return _storage
