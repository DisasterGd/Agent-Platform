"""add conversation pinned

Revision ID: 0003_add_conversation_pinned
Revises: 0002_add_message_attachments
Create Date: 2026-11-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_add_conversation_pinned"
down_revision = "0002_add_message_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("conversations", "pinned")
