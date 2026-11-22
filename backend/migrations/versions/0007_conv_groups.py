"""conv_groups table + conversations.group_id (v0.4.1 分组优化)

Revision ID: 0007_conv_groups
Revises: 0006_memory
Create Date: 2026-11-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_conv_groups"
down_revision = "0006_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conv_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False, server_default="未命名分组"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conv_groups_user_id", "conv_groups", ["user_id"])
    op.create_index("ix_conv_groups_user_updated", "conv_groups", ["user_id", "updated_at"])

    op.add_column("conversations", sa.Column("group_id", sa.Integer(), nullable=True))
    op.create_index("ix_conversations_group_id", "conversations", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_conversations_group_id", table_name="conversations")
    op.drop_column("conversations", "group_id")
    op.drop_index("ix_conv_groups_user_updated", table_name="conv_groups")
    op.drop_index("ix_conv_groups_user_id", table_name="conv_groups")
    op.drop_table("conv_groups")
