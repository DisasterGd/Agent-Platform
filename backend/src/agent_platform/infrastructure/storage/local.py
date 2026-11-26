"""本地文件存储：上传文件与 Agent 生成文件，未来可替换为对象存储。

落盘使用**可读文件名**（与 artifact 显示名、下载链接一致），便于直接翻阅 data 目录：
- 清洗 Windows 非法字符与控制符，去掉路径部分；
- 同名不覆盖，自动追加序号（报告.md → 报告 (2).md）；
- 历史 uuid 命名的文件不受影响，旧链接照常可用。

**v0.7 per-user 目录**：所有方法显式接收 user_id，文件落在 `data/{category}/u{user_id}/` 下——
磁盘目录本身就是归属边界（隔离的第一道墙，下载/预览/删除都按 user 前缀定位）。
- user_id=None 保留旧行为（根目录），仅存量兼容路径与测试使用；
- local 模式下 user 目录未命中时回退读根目录（存量迁移脚本没跑过的旧文件仍可下载；
  cloud 模式不回退——多用户下根目录文件不属于任何请求者）；
- 存量迁移：scripts/migrate_files_to_user_dirs.py，应用启动时也会幂等执行一次。
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path

from agent_platform.config import settings
from agent_platform.infrastructure.filetypes import classify_kind, human_size

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
        # URL 形状不随 per-user 目录变化——归属由服务端按请求者解析，历史链接承诺延续。
        return f"/api/files/{self.category}/{self.stored_name}"

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "url": self.url,
            "content_type": self.content_type,
            "size": self.size,
            "size_label": human_size(self.size),
            # v0.5 资料库：登记与前端展示需要的三件事
            "stored_name": self.stored_name,
            "category": self.category,
            "kind": classify_kind(self.filename, self.content_type),
        }


class LocalStorage:
    def __init__(self, base_dir: Path) -> None:
        self.base = base_dir
        self.uploads = base_dir / "uploads"
        self.generated = base_dir / "generated"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.generated.mkdir(parents=True, exist_ok=True)
        # v0.7：同一进程内 save 互斥（exists() 检查与写入非原子，靠锁缩小并发同名竞态；
        # 跨进程仍由 DB 唯一约束 + 落盘重名序号兜底）
        self._save_lock = threading.Lock()

    def _dir(self, category: str) -> Path:
        return self.uploads if category == "uploads" else self.generated

    def user_dir(self, category: str, user_id: int | None) -> Path:
        """该用户在该类别下的磁盘目录；user_id=None → 根目录（存量兼容/测试）。"""
        base = self._dir(category)
        return base / f"u{int(user_id)}" if user_id else base

    def save(
        self, category: str, filename: str, content: bytes, content_type: str, user_id: int | None = None
    ) -> StoredFile:
        safe_name = _sanitize(filename)
        with self._save_lock:
            directory = self.user_dir(category, user_id)
            directory.mkdir(parents=True, exist_ok=True)
            target = _unique_path(directory, safe_name)
            target.write_bytes(content)
        return StoredFile(
            filename=safe_name,
            stored_name=target.name,  # 可读名；重名时带 " (2)" 之类序号
            category=category,
            content_type=content_type,
            size=len(content),
        )

    def resolve(self, category: str, stored_name: str, user_id: int | None = None) -> Path | None:
        """定位磁盘文件。user 目录优先；local 模式回退根目录（存量迁移未跑的旧文件仍可读）。"""
        # 只允许访问已知目录，且必须是纯文件名（拒绝路径穿越；"a..b.md"这类合法名不误伤）
        if stored_name in ("", ".", "..") or Path(stored_name).name != stored_name:
            return None
        if user_id is not None:
            target = self.user_dir(category, user_id) / stored_name
            if target.is_file():
                return target
            if settings.auth_mode != "local":
                return None
        target = self._dir(category) / stored_name
        return target if target.is_file() else None

    def remove(self, category: str, stored_name: str, user_id: int | None = None) -> bool:
        """删除磁盘文件（资料库删除条目时调用）。文件不存在也视为成功（幂等）。"""
        path = self.resolve(category, stored_name, user_id)
        if path is None:
            return False
        try:
            path.unlink()
        except OSError:
            return False
        return True

    def read_bytes(
        self, category: str, stored_name: str, limit: int | None = None, user_id: int | None = None
    ) -> bytes | None:
        path = self.resolve(category, stored_name, user_id)
        if path is None:
            return None
        try:
            if limit is None:
                return path.read_bytes()
            with path.open("rb") as fh:
                return fh.read(limit)
        except OSError:
            return None

    def iter_files(self, category: str, user_id: int | None = None) -> list[tuple[str, int]]:
        """列目录：(文件名, 字节数)。传 user_id 时只列该用户目录；供资料库扫描存量文件使用。"""
        directory = self.user_dir(category, user_id)
        if not directory.is_dir():
            return []
        out: list[tuple[str, int]] = []
        for entry in directory.iterdir():
            if entry.is_file():
                try:
                    out.append((entry.name, entry.stat().st_size))
                except OSError:
                    continue
        return out

    def usage(self) -> dict[str, int]:
        """磁盘占用统计（admin 用）：根目录 + 所有 u* 用户目录一起算。"""
        counts: dict[str, int] = {}
        for category in ("uploads", "generated"):
            total = 0
            base = self._dir(category)
            if base.is_dir():
                for entry in base.rglob("*"):
                    if entry.is_file():
                        try:
                            total += entry.stat().st_size
                        except OSError:
                            continue
            counts[category] = total
        return counts


_storage: LocalStorage | None = None


def get_storage() -> LocalStorage:
    global _storage
    if _storage is None:
        _storage = LocalStorage(Path(settings.storage_dir))
    return _storage
