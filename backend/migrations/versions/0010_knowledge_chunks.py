"""knowledge_chunks table (v0.6.1 知识库切块与检索，v0.5 收尾)

Revision ID: 0010_knowledge_chunks
Revises: 0009_file_assets
Create Date: 2026-11-23

资料库中文本类文件的检索单元：asset_id 外键 CASCADE（删文件即清块），
(user_id) 与 (asset_id, chunk_index) 建索引供检索与重建去重。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_knowledge_chunks"
down_revision = "0009_file_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("char_len", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["file_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_chunks_asset_index", "knowledge_chunks", ["asset_id", "chunk_index"])
    op.create_index("ix_knowledge_chunks_user", "knowledge_chunks", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_user", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_asset_index", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
