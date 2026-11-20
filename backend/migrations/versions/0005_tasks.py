"""tasks and task_steps tables (v0.3 任务规划与执行)

Revision ID: 0005_tasks
Revises: 0004_message_variants
Create Date: 2026-11-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_tasks"
down_revision = "0004_message_variants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="awaiting_approval"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"])
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])
    op.create_index("ix_tasks_conversation_id", "tasks", ["conversation_id"])
    op.create_index("ix_tasks_user_created", "tasks", ["user_id", "created_at"])

    op.create_table(
        "task_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("artifacts", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_steps_task_id", "task_steps", ["task_id"])
    op.create_index("ix_task_steps_task_idx", "task_steps", ["task_id", "idx"])


def downgrade() -> None:
    op.drop_index("ix_task_steps_task_idx", table_name="task_steps")
    op.drop_index("ix_task_steps_task_id", table_name="task_steps")
    op.drop_table("task_steps")
    op.drop_index("ix_tasks_user_created", table_name="tasks")
    op.drop_index("ix_tasks_conversation_id", table_name="tasks")
    op.drop_index("ix_tasks_project_id", table_name="tasks")
    op.drop_index("ix_tasks_user_id", table_name="tasks")
    op.drop_table("tasks")
