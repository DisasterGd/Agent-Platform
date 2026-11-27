"""v0.8 部署级配置（deployment_settings 表）"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_deployment_settings"
down_revision = "0013_local_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployment_settings",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("deployment_settings")
