"""v0.7 账号体系：users 扩列 + sessions/auth_codes/user_settings 三表 + file_assets 唯一约束随用户走

Revision ID: 0012_auth_accounts
Revises: 0011_chunk_embeddings
Create Date: 2026-11-26

- users：email（cloud 模式登录身份，local 保持 NULL）+ display_name/is_admin/status/last_login_at；
- sessions：服务端会话表，cookie 只放随机 token、库存 SHA-256（可撤销、封号即时生效）；
- auth_codes：一次性邮箱验证码（哈希落库、10 分钟有效、错 5 次作废），行本身兼作频控依据；
- user_settings：cloud 模式的个人设置（settings.json v3 同构 JSON），local 不用；
- file_assets 唯一约束 (category, stored_name) → (user_id, category, stored_name)：
  配合 per-user 目录（data/{category}/u{user_id}/），存量文件由 scripts/migrate_files_to_user_dirs.py
  搬入 u{dev_user_id}/（启动时也会自动幂等执行一次）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_auth_accounts"
down_revision = "0011_chunk_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- users 扩列 ----
    op.add_column("users", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("display_name", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("users", sa.Column("status", sa.String(length=16), nullable=False, server_default="active"))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ---- 会话 ----
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    # ---- 一次性验证码 ----
    op.create_table(
        "auth_codes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=24), nullable=False, server_default="login"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_ip", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_codes_email", "auth_codes", ["email"])
    op.create_index("ix_auth_codes_email_created", "auth_codes", ["email", "created_at"])

    # ---- 个人设置（cloud 模式）----
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    # ---- 文件唯一约束：全局 → 按用户（per-user 目录）----
    op.drop_constraint("uq_file_assets_category_stored", "file_assets", type_="unique")
    op.create_unique_constraint(
        "uq_file_assets_user_category_stored", "file_assets", ["user_id", "category", "stored_name"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_file_assets_user_category_stored", "file_assets", type_="unique")
    op.create_unique_constraint("uq_file_assets_category_stored", "file_assets", ["category", "stored_name"])

    op.drop_table("user_settings")
    op.drop_index("ix_auth_codes_email_created", table_name="auth_codes")
    op.drop_index("ix_auth_codes_email", table_name="auth_codes")
    op.drop_table("auth_codes")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "status")
    op.drop_column("users", "is_admin")
    op.drop_column("users", "display_name")
    op.drop_column("users", "email")
