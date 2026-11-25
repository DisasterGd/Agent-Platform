"""知识库切块仓储（唯一 DB 访问点，v0.6.1）。"""
from __future__ import annotations

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from agent_platform.infrastructure.database.models import FileAsset, KnowledgeChunk


def _like_escape(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class KnowledgeRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def replace_for_asset(self, asset: FileAsset, chunks: list[str]) -> int:
        """整文件重建：先删旧块再插新块（幂等，重复调用安全）。"""
        self.db.query(KnowledgeChunk).filter(KnowledgeChunk.asset_id == asset.id).delete()
        for idx, text in enumerate(chunks):
            self.db.add(
                KnowledgeChunk(
                    user_id=asset.user_id, asset_id=asset.id,
                    chunk_index=idx, content=text, char_len=len(text),
                )
            )
        self.db.commit()
        return len(chunks)

    def asset_ids_with_chunks(self, user_id: int) -> set[int]:
        rows = (
            self.db.query(KnowledgeChunk.asset_id)
            .filter(KnowledgeChunk.user_id == user_id)
            .distinct()
            .all()
        )
        return {int(r[0]) for r in rows}

    def count_for_user(self, user_id: int) -> int:
        return int(
            self.db.query(func.count(KnowledgeChunk.id))
            .filter(KnowledgeChunk.user_id == user_id)
            .scalar() or 0
        )

    def candidates(
        self, user_id: int, terms: list[str], *, project_id: int | None = None, limit: int = 400,
    ) -> list[tuple[KnowledgeChunk, FileAsset]]:
        """LIKE 预取候选块（真正的排序打分在服务层 Python 里做），联查档案取文件名与归属。

        只检索用户上传的资料（source=upload）——Agent 生成的交付物不算“用户的知识”。
        """
        conds = [
            func.lower(KnowledgeChunk.content).like(f"%{_like_escape(t.lower())}%", escape="\\")
            for t in terms
        ]
        query = (
            self.db.query(KnowledgeChunk, FileAsset)
            .join(FileAsset, FileAsset.id == KnowledgeChunk.asset_id)
            .filter(KnowledgeChunk.user_id == user_id, or_(*conds), FileAsset.source == "upload")
        )
        if project_id is not None:
            query = query.filter(FileAsset.project_id == project_id)
        return query.order_by(KnowledgeChunk.asset_id, KnowledgeChunk.chunk_index).limit(limit).all()

    def upload_assets_without_chunks(self, user_id: int) -> list[FileAsset]:
        """还没切块的上传文件（反连接）——重建索引的扫描清单，不受列表分页上限约束。"""
        has_chunks = (
            self.db.query(KnowledgeChunk.id)
            .filter(KnowledgeChunk.asset_id == FileAsset.id)
            .exists()
        )
        query = (
            self.db.query(FileAsset)
            .filter(
                FileAsset.user_id == user_id,
                FileAsset.source == "upload",
                ~has_chunks,
            )
            .order_by(FileAsset.id)
        )
        return list(query.all())

    def delete_for_asset(self, asset_id: int) -> int:
        """显式清理（正常路径靠 file_assets 的 CASCADE，这里给重索引失败等场景兜底）。"""
        n = self.db.query(KnowledgeChunk).filter(KnowledgeChunk.asset_id == asset_id).delete()
        self.db.commit()
        return int(n)
