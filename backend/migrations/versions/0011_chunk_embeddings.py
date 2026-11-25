"""knowledge_chunks 向量列（v0.6.2 向量检索升级）

Revision ID: 0011_chunk_embeddings
Revises: 0010_knowledge_chunks
Create Date: 2026-11-25

embedding_model 记向量出自哪个嵌入模型，embedding 存 JSON 数值数组（MySQL JSON / SQLite TEXT 通用）。
两列都可空/默认空：升级前已切块的文件关键词检索照常可用，启用嵌入角色后经“重建索引”补向量；
换嵌入模型＝旧向量作废（维度与空间不可比），重算后覆盖。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_chunk_embeddings"
down_revision = "0010_knowledge_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_chunks",
        sa.Column("embedding_model", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column("embedding", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_chunks", "embedding")
    op.drop_column("knowledge_chunks", "embedding_model")
