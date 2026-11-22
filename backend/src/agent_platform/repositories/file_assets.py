"""资料库数据读写（v0.5）：file_assets 表的唯一访问入口。

约定：
- `(category, stored_name)` 唯一，`create` 幂等（同磁盘文件重复登记返回既有行）；
- 重命名只改 `filename`（显示名），`stored_name` 是磁盘真实名，改了会让历史链接失效；
- 项目归属用普通整型列（与 conversations.project_id 一致），随项目移动更新。
"""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import FileAsset

# “未传该字段”哨兵（None 表示显式移出项目）
UNSET = object()

MAX_LIST_LIMIT = 500


class FileAssetRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        user_id: int,
        category: str,
        stored_name: str,
        filename: str,
        *,
        content_type: str = "",
        kind: str = "other",
        size: int = 0,
        source: str = "upload",
        tool: str = "",
        project_id: int | None = None,
        conversation_id: int | None = None,
    ) -> FileAsset:
        """幂等登记：同一磁盘文件重复登记返回既有记录（扫描存量与工具并发都靠它兜底）。"""
        existing = self.find(category, stored_name)
        if existing is not None:
            return existing
        asset = FileAsset(
            user_id=user_id,
            category=category,
            stored_name=stored_name[:255],
            filename=filename[:255],
            content_type=content_type[:128],
            kind=kind,
            size=size,
            source=source,
            tool=tool[:32],
            project_id=project_id,
            conversation_id=conversation_id,
        )
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def get(self, asset_id: int) -> FileAsset | None:
        return self.db.get(FileAsset, asset_id)

    def find(self, category: str, stored_name: str) -> FileAsset | None:
        stmt = select(FileAsset).where(
            FileAsset.category == category, FileAsset.stored_name == stored_name
        )
        return self.db.scalars(stmt).first()

    def _filtered(
        self,
        user_id: int,
        *,
        project_id: int | None | object,
        kind: str | None,
        category: str | None,
        source: str | None,
        keyword: str | None,
    ):
        """列表与计数共用的过滤条件（保证 total / matched 口径一致）。"""
        stmt = select(FileAsset).where(FileAsset.user_id == user_id)
        if project_id is not UNSET:
            stmt = stmt.where(FileAsset.project_id == project_id)
        if kind:
            stmt = stmt.where(FileAsset.kind == kind)
        if category:
            stmt = stmt.where(FileAsset.category == category)
        if source:
            stmt = stmt.where(FileAsset.source == source)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                or_(FileAsset.filename.like(like), FileAsset.stored_name.like(like))
            )
        return stmt

    def list_by_user(
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
    ) -> list[FileAsset]:
        stmt = self._filtered(
            user_id,
            project_id=project_id,
            kind=kind,
            category=category,
            source=source,
            keyword=keyword,
        )
        stmt = stmt.order_by(FileAsset.created_at.desc(), FileAsset.id.desc())
        stmt = stmt.limit(max(1, min(int(limit), MAX_LIST_LIMIT))).offset(max(0, int(offset)))
        return list(self.db.scalars(stmt))

    def count_filtered(
        self,
        user_id: int,
        *,
        project_id: int | None | object = UNSET,
        kind: str | None = None,
        category: str | None = None,
        source: str | None = None,
        keyword: str | None = None,
    ) -> int:
        """筛选后的条数（不受 limit/offset 影响）。"""
        stmt = self._filtered(
            user_id,
            project_id=project_id,
            kind=kind,
            category=category,
            source=source,
            keyword=keyword,
        )
        return int(self.db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())

    def count_by_kind(self, user_id: int) -> dict[str, int]:
        """页签角标：按 kind 统计（不含筛选条件，供前端显示总量）。"""
        stmt = (
            select(FileAsset.kind, func.count(FileAsset.id))
            .where(FileAsset.user_id == user_id)
            .group_by(FileAsset.kind)
        )
        return {str(k): int(c) for k, c in self.db.execute(stmt)}

    def count_by_category(self, user_id: int) -> dict[str, int]:
        stmt = (
            select(FileAsset.category, func.count(FileAsset.id))
            .where(FileAsset.user_id == user_id)
            .group_by(FileAsset.category)
        )
        return {str(k): int(c) for k, c in self.db.execute(stmt)}

    def count_by_project(self, user_id: int) -> list[dict[str, object]]:
        """“文件夹”视图：按项目分组的文件数（project_id 为 None 表示未归类）。

        返回 [{project_id, count}] 而不是 {project_id: count} 字典：
        None 作为字典键会被 JSON 编码成 "None"，前端拿到的是字符串键，容易出错。
        """
        stmt = (
            select(FileAsset.project_id, func.count(FileAsset.id))
            .where(FileAsset.user_id == user_id)
            .group_by(FileAsset.project_id)
        )
        return [{"project_id": k, "count": int(c)} for k, c in self.db.execute(stmt)]

    def total(self, user_id: int) -> int:
        stmt = select(func.count(FileAsset.id)).where(FileAsset.user_id == user_id)
        return int(self.db.execute(stmt).scalar_one())

    def update(
        self,
        asset_id: int,
        *,
        filename: str | None = None,
        kind: str | None = None,
        project_id: int | None | object = UNSET,
        conversation_id: int | None | object = UNSET,
    ) -> FileAsset | None:
        asset = self.db.get(FileAsset, asset_id)
        if asset is None:
            return None
        if filename is not None and filename.strip():
            asset.filename = filename.strip()[:255]
        if kind is not None:
            asset.kind = kind
        if project_id is not UNSET:
            asset.project_id = project_id  # type: ignore[assignment]
        if conversation_id is not UNSET:
            asset.conversation_id = conversation_id  # type: ignore[assignment]
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def link_uploads(self, stored_names: list[str], conversation_id: int, project_id: int | None) -> int:
        """消息落库时把附件对应的上传记录归到该会话/项目（上传时还不知道会归属谁）。"""
        if not stored_names:
            return 0
        stmt = select(FileAsset).where(
            FileAsset.category == "uploads", FileAsset.stored_name.in_(stored_names)
        )
        rows = list(self.db.scalars(stmt))
        for asset in rows:
            asset.conversation_id = conversation_id
            if project_id is not None:
                asset.project_id = project_id
        self.db.commit()
        return len(rows)

    def delete(self, asset_id: int) -> bool:
        asset = self.db.get(FileAsset, asset_id)
        if asset is None:
            return False
        self.db.delete(asset)
        self.db.commit()
        return True
