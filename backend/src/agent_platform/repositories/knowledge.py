"""知识库切块仓储（唯一 DB 访问点，v0.6.1）。"""
from __future__ import annotations

from sqlalchemy import and_, func, or_
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

        只检索用户上传的资料（category=uploads）——Agent 生成的交付物不算“用户的知识”。
        口径用目录而非 source：source 记录的是登记方式（上传接口=upload，v0.5 前存量扫描=library），
        老文件若只按 source=upload 筛会被“内容索引”永远漏掉（v0.6.2 修复）。
        """
        conds = [
            func.lower(KnowledgeChunk.content).like(f"%{_like_escape(t.lower())}%", escape="\\")
            for t in terms
        ]
        query = (
            self.db.query(KnowledgeChunk, FileAsset)
            .join(FileAsset, FileAsset.id == KnowledgeChunk.asset_id)
            .filter(KnowledgeChunk.user_id == user_id, or_(*conds), FileAsset.category == "uploads")
        )
        if project_id is not None:
            query = query.filter(FileAsset.project_id == project_id)
        return query.order_by(KnowledgeChunk.asset_id, KnowledgeChunk.chunk_index).limit(limit).all()

    def upload_assets_without_chunks(self, user_id: int) -> list[FileAsset]:
        """还没切块的上传文件（反连接）——重建索引的扫描清单，不受列表分页上限约束。

        判据是 category=uploads 而非 source：source 只记登记方式（上传接口/存量扫描），
        按 source 筛会漏掉 v0.5 前上传、后被扫描登记的历史文件。
        """
        has_chunks = (
            self.db.query(KnowledgeChunk.id)
            .filter(KnowledgeChunk.asset_id == FileAsset.id)
            .exists()
        )
        query = (
            self.db.query(FileAsset)
            .filter(
                FileAsset.user_id == user_id,
                FileAsset.category == "uploads",
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

    # ---------- 向量（v0.6.2） ----------

    def chunks_without_vectors(self, model: str, *, user_id: int | None = None, asset_id: int | None = None) -> list[KnowledgeChunk]:
        """待（重）嵌入的块：没有向量，或向量出自别的模型（换模型=旧向量不可比，整体作废重算）。"""
        stale = and_(KnowledgeChunk.embedding.is_not(None), KnowledgeChunk.embedding_model != model)
        query = self.db.query(KnowledgeChunk).filter(
            or_(KnowledgeChunk.embedding.is_(None), stale),
        )
        if user_id is not None:
            query = query.filter(KnowledgeChunk.user_id == user_id)
        if asset_id is not None:
            query = query.filter(KnowledgeChunk.asset_id == asset_id)
        return list(query.order_by(KnowledgeChunk.asset_id, KnowledgeChunk.chunk_index).all())

    def set_embeddings(self, items: list[tuple[int, list[float]]], model: str) -> int:
        """批量写回向量（嵌入成功后由服务层调用）；items 为 (chunk_id, vector)。"""
        for chunk_id, vec in items:
            self.db.query(KnowledgeChunk).filter(KnowledgeChunk.id == chunk_id).update(
                {"embedding": vec, "embedding_model": model}, synchronize_session=False,
            )
        self.db.commit()
        return len(items)

    def vectors_for_user(
        self, user_id: int, model: str, *, project_id: int | None = None,
    ) -> list[tuple[int, int, int, list[float]]]:
        """(chunk_id, asset_id, chunk_index, vector)：只取指定模型产出的非空向量。

        刻意不带 content 大字段——hybrid 打分只需要向量本身。
        只取上传资料的块（与 candidates / upload_assets_without_chunks 同一口径：category=uploads，
        生成产物不算“用户的知识”）。
        """
        query = (
            self.db.query(KnowledgeChunk.id, KnowledgeChunk.asset_id,
                          KnowledgeChunk.chunk_index, KnowledgeChunk.embedding)
            .join(FileAsset, FileAsset.id == KnowledgeChunk.asset_id)
            .filter(
                KnowledgeChunk.user_id == user_id,
                KnowledgeChunk.embedding.is_not(None),
                KnowledgeChunk.embedding_model == model,
                FileAsset.category == "uploads",
            )
        )
        if project_id is not None:
            query = query.filter(FileAsset.project_id == project_id)
        return [(int(r[0]), int(r[1]), int(r[2]), list(r[3])) for r in query.all()]

    def rows_by_ids(self, chunk_ids: list[int]) -> list[tuple[KnowledgeChunk, FileAsset]]:
        """语义-only 命中的补取：按块 id 拿 (chunk, asset) 行，供片段与资料库信息展示。"""
        if not chunk_ids:
            return []
        return (
            self.db.query(KnowledgeChunk, FileAsset)
            .join(FileAsset, FileAsset.id == KnowledgeChunk.asset_id)
            .filter(KnowledgeChunk.id.in_(chunk_ids))
            .all()
        )
