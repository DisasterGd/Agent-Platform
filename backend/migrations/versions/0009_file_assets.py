"""file_assets table (v0.5 资料库：文件登记与项目联动)

Revision ID: 0009_file_assets
Revises: 0008_group_kind
Create Date: 2026-11-22

一行对应磁盘上一个文件：stored_name 为真实文件名（重命名只改 filename，历史链接继续有效），
(category, stored_name) 唯一，使“上传登记 / 生成登记 / 存量扫描”三条入口可以重复调用。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_file_assets"
down_revision = "0008_group_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(16), nullable=False, server_default="generated"),
        sa.Column("stored_name", sa.String(255), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False, server_default=""),
        sa.Column("kind", sa.String(16), nullable=False, server_default="other"),
        sa.Column("source", sa.String(16), nullable=False, server_default="upload"),
        sa.Column("tool", sa.String(32), nullable=False, server_default=""),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("category", "stored_name", name="uq_file_assets_category_stored"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_file_assets_user_id", "file_assets", ["user_id"])
    op.create_index("ix_file_assets_project_id", "file_assets", ["project_id"])
    op.create_index("ix_file_assets_conversation_id", "file_assets", ["conversation_id"])
    op.create_index("ix_file_assets_user_created", "file_assets", ["user_id", "created_at"])
    op.create_index("ix_file_assets_project_created", "file_assets", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_file_assets_project_created", table_name="file_assets")
    op.drop_index("ix_file_assets_user_created", table_name="file_assets")
    op.drop_index("ix_file_assets_conversation_id", table_name="file_assets")
    op.drop_index("ix_file_assets_project_id", table_name="file_assets")
    op.drop_index("ix_file_assets_user_id", table_name="file_assets")
    op.drop_table("file_assets")
