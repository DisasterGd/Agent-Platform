"""message variants for regenerate (重新生成保留历史版本)

Revision ID: 0004_message_variants
Revises: 0003_add_conversation_pinned
Create Date: 2026-11-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_message_variants"
down_revision = "0003_add_conversation_pinned"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("group_id", sa.Integer(), nullable=True))
    op.add_column(
        "messages",
        sa.Column("variant_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_messages_group_id", "messages", ["group_id"])
    # 历史消息各自成为单版本链：group_id 指向自身
    op.execute("UPDATE messages SET group_id = id WHERE group_id IS NULL")


def downgrade() -> None:
    op.drop_index("ix_messages_group_id", table_name="messages")
    op.drop_column("messages", "variant_index")
    op.drop_column("messages", "group_id")
