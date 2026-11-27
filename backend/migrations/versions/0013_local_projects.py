"""v0.7.4 本地项目：local_projects 表 + conversations.local_project_id（伪编辑器，仅 local 模式）

Revision ID: 0013_local_projects
Revises: 0012_auth_accounts
Create Date: 2026-11-27

- local_projects：机器上真实目录的注册记录（user_id + root_path 唯一），allow_write 为
  v0.7.6 工具注入的项目级写入开关；注销只删行、绝不动磁盘。
- conversations.local_project_id：与 project_id 互斥的服务层约束；FK ON DELETE SET NULL，
  注销本地项目后会话保留（脱离项目）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_local_projects"
down_revision = "0012_auth_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_projects",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("root_path", sa.String(length=500), nullable=False),
        sa.Column("allow_write", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "root_path", name="uq_local_projects_user_root"),
    )
    op.create_index("ix_local_projects_user_id", "local_projects", ["user_id"])
    op.create_index("ix_local_projects_user_updated", "local_projects", ["user_id", "updated_at"])

    op.add_column(
        "conversations",
        sa.Column("local_project_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_conversations_local_project_id", "conversations", ["local_project_id"])
    op.create_foreign_key(
        "fk_conversations_local_project", "conversations", "local_projects",
        ["local_project_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_conversations_local_project", "conversations", type_="foreignkey")
    op.drop_index("ix_conversations_local_project_id", table_name="conversations")
    op.drop_column("conversations", "local_project_id")
    op.drop_index("ix_local_projects_user_updated", table_name="local_projects")
    op.drop_index("ix_local_projects_user_id", table_name="local_projects")
    op.drop_table("local_projects")
