"""projects + memories tables, conversation summary columns (v0.4 记忆系统)

Revision ID: 0006_memory
Revises: 0005_tasks
Create Date: 2026-11-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_memory"
down_revision = "0005_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # v0.4 会话记忆：超长历史自动压缩的摘要
    # （MySQL 的 TEXT 列不允许 DEFAULT：不带 server_default，存量行由 MySQL 隐式补空串）
    op.add_column("conversations", sa.Column("summary", sa.Text(), nullable=False))
    op.add_column(
        "conversations",
        sa.Column("summary_covered_id", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False, server_default="未命名项目"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])
    op.create_index("ix_projects_user_updated", "projects", ["user_id", "updated_at"])

    op.create_table(
        "memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False, server_default="global"),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(50), nullable=False, server_default="其他"),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="auto"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memories_user_id", "memories", ["user_id"])
    op.create_index("ix_memories_project_id", "memories", ["project_id"])
    op.create_index("ix_memories_user_scope", "memories", ["user_id", "scope"])


def downgrade() -> None:
    op.drop_index("ix_memories_user_scope", table_name="memories")
    op.drop_index("ix_memories_project_id", table_name="memories")
    op.drop_index("ix_memories_user_id", table_name="memories")
    op.drop_table("memories")
    op.drop_index("ix_projects_user_updated", table_name="projects")
    op.drop_index("ix_projects_user_id", table_name="projects")
    op.drop_table("projects")
    op.drop_column("conversations", "summary_covered_id")
    op.drop_column("conversations", "summary")
