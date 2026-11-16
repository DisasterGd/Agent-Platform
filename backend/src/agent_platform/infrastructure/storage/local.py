"""本地文件存储：上传文件与 Agent 生成文件，未来可替换为对象存储。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from agent_platform.config import settings


@dataclass
class StoredFile:
    filename: str       # 原始文件名
    stored_name: str    # 磁盘上的唯一文件名
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
        safe_name = Path(filename).name or "file"
        ext = Path(safe_name).suffix.lower()
        stored_name = f"{uuid.uuid4().hex}{ext}"
        target = self._dir(category) / stored_name
        target.write_bytes(content)
        return StoredFile(
            filename=safe_name,
            stored_name=stored_name,
            category=category,
            content_type=content_type,
            size=len(content),
        )

    def resolve(self, category: str, stored_name: str) -> Path | None:
        # 只允许访问已知目录，且文件名不能包含路径分隔符
        if "/" in stored_name or "\\" in stored_name or ".." in stored_name:
            return None
        target = self._dir(category) / stored_name
        return target if target.is_file() else None


_storage: LocalStorage | None = None


def get_storage() -> LocalStorage:
    global _storage
    if _storage is None:
        _storage = LocalStorage(Path(settings.storage_dir))
    return _storage
