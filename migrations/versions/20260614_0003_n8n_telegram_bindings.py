"""Add n8n Telegram bindings.

Revision ID: 20260614_0003
Revises: 20260613_0002
Create Date: 2026-06-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260614_0003"
down_revision = "20260613_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "n8n_telegram_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("telegram_user_id", sa.String(length=255), nullable=False),
        sa.Column("telegram_chat_id", sa.String(length=255), nullable=True),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("telegram_user_id", name="uq_n8n_telegram_binding_user"),
    )
    op.create_index(
        "ix_n8n_telegram_bindings_lookup",
        "n8n_telegram_bindings",
        ["telegram_user_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_n8n_telegram_bindings_lookup", table_name="n8n_telegram_bindings")
    op.drop_table("n8n_telegram_bindings")
