"""conv_groups.kind (v0.4.1 任务子分组：group=根级自定义分组 / task=任务分区子分组)

Revision ID: 0008_group_kind
Revises: 0007_conv_groups
Create Date: 2026-11-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_group_kind"
down_revision = "0007_conv_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conv_groups",
        sa.Column("kind", sa.String(16), nullable=False, server_default="group"),
    )


def downgrade() -> None:
    op.drop_column("conv_groups", "kind")
