"""资料库业务用例（v0.5）：文件登记、查看、重命名、移动项目、删除、预览、存量扫描。

三条登记入口共用同一漏斗：
- 上传接口（routes/files.py）→ register_saved(source="upload")；
- 聊天/任务事件流里的 artifact_ready → register_artifact(source="chat"/"task")；
- 首次打开资料库时的存量扫描 → register_saved(source="library")。

磁盘是唯一事实来源，表里只存“哪个文件是什么、归谁”：删除会真的删文件（界面二次确认），
重命名只改显示名，不动磁盘名，因此历史链接与消息里的卡片继续可用。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from agent_platform.infrastructure import filetypes as ft
from agent_platform.infrastructure.attachments import parse_file_url
from agent_platform.infrastructure.generation.textfiles import list_zip_entries
from agent_platform.infrastructure.storage.local import StoredFile, get_storage
from agent_platform.repositories.file_assets import UNSET, FileAssetRepository
from agent_platform.repositories.projects import ProjectRepository

PREVIEW_TEXT_BYTES = 1024 * 1024      # 预览最多读 1MB 文本
PREVIEW_LINES = 2000                  # 再多就截断，避免整屏卡顿


class LibraryService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.assets = FileAssetRepository(db)
        self.projects = ProjectRepository(db)

    # ---------- 登记 ----------

    def register_saved(
        self,
        stored: StoredFile,
        *,
        user_id: int,
        source: str = "upload",
        project_id: int | None = None,
        conversation_id: int | None = None,
        tool: str = "",
    ) -> dict[str, Any]:
        """把刚落盘的文件登记进资料库（幂等）。"""
        asset = self.assets.create(
            user_id,
            stored.category,
            stored.stored_name,
            stored.filename,
            content_type=stored.content_type,
            kind=ft.classify_kind(stored.filename, stored.content_type),
            size=stored.size,
            source=source,
            tool=tool,
            project_id=project_id,
            conversation_id=conversation_id,
        )
        return self._to_out(asset)

    def register_artifact(
        self,
        artifact: dict[str, Any],
        *,
        user_id: int,
        source: str = "chat",
        project_id: int | None = None,
        conversation_id: int | None = None,
    ) -> dict[str, Any] | None:
        """工具产出（artifact_ready 事件）登记：按 url 找回磁盘文件补全类型与体积。"""
        parsed = parse_file_url(str(artifact.get("url", "")))
        if parsed is None:
            return None
        category, stored_name = parsed
        filename = str(artifact.get("filename") or stored_name)
        content_type = str(artifact.get("content_type") or "") or ft.content_type_for(filename)
        path = get_storage().resolve(category, stored_name)
        size = int(artifact.get("size") or 0)
        if not size and path is not None:
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
        return self.register_saved(
            StoredFile(
                filename=filename,
                stored_name=stored_name,
                category=category,
                content_type=content_type,
                size=size,
            ),
            user_id=user_id,
            source=source,
            project_id=project_id,
            conversation_id=conversation_id,
            tool=str(artifact.get("tool") or ""),
        )

    def link_attachments(
        self, attachments: list[dict], *, conversation_id: int, project_id: int | None
    ) -> int:
        """消息落库后补写归属：上传附件在上传时还不知道会进哪个会话/项目。"""
        names: list[str] = []
        for att in attachments:
            parsed = parse_file_url(str(att.get("url", "")))
            if parsed and parsed[0] == "uploads":
                names.append(parsed[1])
        if not names:
            return 0
        return self.assets.link_uploads(names, conversation_id, project_id)

    def scan_existing(self, user_id: int) -> int:
        """存量扫描：把磁盘上有、表里没有的历史文件登记为“未归类”资料库条目。"""
        registered = 0
        for category in ("uploads", "generated"):
            for name, size in get_storage().iter_files(category):
                if self.assets.find(category, name) is not None:
                    continue
                self.assets.create(
                    user_id,
                    category,
                    name,
                    name,
                    content_type=ft.content_type_for(name),
                    kind=ft.classify_kind(name),
                    size=size,
                    source="library",
                )
                registered += 1
        return registered

    # ---------- 查询 ----------

    def list(
        self,
        user_id: int,
        *,
        project_id: int | None | object = UNSET,
        kind: str | None = None,
        category: str | None = None,
        source: str | None = None,
        keyword: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        items = self.assets.list_by_user(
            user_id,
            project_id=project_id,
            kind=kind,
            category=category,
            source=source,
            keyword=keyword,
            limit=limit,
            offset=offset,
        )
        # 一次性列出目录做存在性判断，避免逐条 stat
        present = {
            category: {name for name, _ in get_storage().iter_files(category)}
            for category in ("uploads", "generated")
        }
        return {
            "items": [self._to_out(a, present.get(a.category, set())) for a in items],
            # total = 全库条数；matched = 当前筛选下的条数（前端标题栏两者都要，否则会误以为筛选没生效）
            "total": self.assets.total(user_id),
            "matched": self.assets.count_filtered(
                user_id,
                project_id=project_id,
                kind=kind,
                category=category,
                source=source,
                keyword=keyword,
            ),
            "kinds": self.assets.count_by_kind(user_id),
            "categories": self.assets.count_by_category(user_id),
            "projects": self.assets.count_by_project(user_id),
        }

    def get(self, asset_id: int, user_id: int) -> dict[str, Any] | None:
        asset = self.assets.get(asset_id)
        if asset is None or asset.user_id != user_id:
            return None
        return self._to_out(asset)

    def display_name(self, category: str, stored_name: str) -> str | None:
        """下载用的显示名：资料库里有记录就用它（重命名后下载得到新名），否则 None。"""
        asset = self.assets.find(category, stored_name)
        return asset.filename if asset is not None else None

    def preview(self, asset_id: int, user_id: int) -> dict[str, Any] | None:
        """预览：图像直接给 url；压缩包给目录树；文本类给正文（截断）；其余只给下载。"""
        asset = self.assets.get(asset_id)
        if asset is None or asset.user_id != user_id:
            return None
        out = self._to_out(asset)
        data = get_storage().read_bytes(asset.category, asset.stored_name, PREVIEW_TEXT_BYTES)
        if data is None:
            return {**out, "preview": "missing"}
        if asset.kind == "image":
            return {**out, "preview": "image"}
        if asset.kind == "audio":
            return {**out, "preview": "audio"}
        if asset.kind == "video":
            return {**out, "preview": "video"}
        if asset.kind == "archive" and ft.suffix_of(asset.filename) == "zip":
            entries = list_zip_entries(get_storage().read_bytes(asset.category, asset.stored_name) or b"")
            return {
                **out,
                "preview": "archive",
                "entries": entries[:400],
                "entry_count": len(entries),
            }
        if ft.is_readable_text(asset.filename, data, asset.content_type):
            text = self._decode(data)
            lines = text.split("\n")
            clipped = len(lines) > PREVIEW_LINES or len(data) >= PREVIEW_TEXT_BYTES
            return {
                **out,
                "preview": "text",
                "content": "\n".join(lines[:PREVIEW_LINES]),
                "truncated": clipped,
                "line_count": len(lines),
            }
        if asset.kind == "document" and ft.suffix_of(asset.filename) in ("pdf", "docx"):
            return {**out, "preview": "binary"}
        return {**out, "preview": "binary"}

    # ---------- 修改 ----------

    def rename(self, asset_id: int, user_id: int, filename: str) -> dict[str, Any] | None:
        asset = self.assets.get(asset_id)
        if asset is None or asset.user_id != user_id:
            return None
        name = (filename or "").strip()
        if not name:
            return self._to_out(asset)
        # 用户可能只输了主干：补回原后缀，避免丢掉类型识别（.py → 无后缀 → 归到“其他”）
        if not ft.suffix_of(name) and ft.suffix_of(asset.filename):
            name = f"{name}.{ft.suffix_of(asset.filename)}"
        name = name[:255]
        updated = self.assets.update(
            asset_id, filename=name, kind=ft.classify_kind(name, asset.content_type)
        )
        return self._to_out(updated) if updated is not None else None

    def move_project(
        self, asset_id: int, user_id: int, project_id: int | None
    ) -> dict[str, Any] | None:
        asset = self.assets.get(asset_id)
        if asset is None or asset.user_id != user_id:
            return None
        if project_id is not None:
            project = self.projects.get(int(project_id))
            if project is None or project.user_id != user_id:
                raise ValueError("项目不存在")
        return self._to_out(self.assets.update(asset_id, project_id=project_id))

    def delete(self, asset_id: int, user_id: int, *, remove_file: bool = True) -> bool:
        """删除条目；默认连同磁盘文件一起删（界面会二次确认）。"""
        asset = self.assets.get(asset_id)
        if asset is None or asset.user_id != user_id:
            return False
        if remove_file:
            get_storage().remove(asset.category, asset.stored_name)
        return self.assets.delete(asset_id)

    def bulk_delete(self, asset_ids: list[int], user_id: int, *, remove_file: bool = True) -> int:
        deleted = 0
        for asset_id in asset_ids:
            if self.delete(int(asset_id), user_id, remove_file=remove_file):
                deleted += 1
        return deleted

    # ---------- 内部 ----------

    @staticmethod
    def _decode(data: bytes) -> str:
        for enc in ("utf-8", "gbk", "utf-16"):
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _to_out(asset: Any, present: set[str] | None = None) -> dict[str, Any]:
        exists = True
        if present is not None:
            exists = asset.stored_name in present
        return {
            "id": asset.id,
            "user_id": asset.user_id,
            "project_id": asset.project_id,
            "conversation_id": asset.conversation_id,
            "category": asset.category,
            "stored_name": asset.stored_name,
            "filename": asset.filename,
            "url": f"/api/files/{asset.category}/{asset.stored_name}",
            "content_type": asset.content_type,
            "kind": asset.kind,
            "kind_label": ft.kind_label(asset.kind),
            "badge": ft.badge_label(asset.filename),
            "source": asset.source,
            "tool": asset.tool,
            "size": asset.size,
            "size_label": ft.human_size(asset.size or 0),
            "missing": not exists,
            "created_at": asset.created_at,
            "updated_at": asset.updated_at,
        }
