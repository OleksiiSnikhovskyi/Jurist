"""Add n8n intake package tables.

Revision ID: 20260613_0002
Revises: 20260612_0001
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260613_0002"
down_revision = "20260612_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "n8n_intake_packages",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("external_chat_id", sa.String(length=255), nullable=True),
        sa.Column("external_user_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("requested_agent", sa.String(length=100), nullable=True),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_n8n_intake_packages_lookup",
        "n8n_intake_packages",
        ["channel", "external_chat_id", "status"],
    )

    op.create_table(
        "n8n_intake_items",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "package_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("n8n_intake_packages.id"),
            nullable=False,
        ),
        sa.Column("item_type", sa.String(length=50), nullable=False),
        sa.Column("external_file_id", sa.String(length=500), nullable=True),
        sa.Column("file_name", sa.String(length=500), nullable=True),
        sa.Column("mime_type", sa.String(length=200), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_n8n_intake_items_package_id", "n8n_intake_items", ["package_id"])


def downgrade() -> None:
    op.drop_index("ix_n8n_intake_items_package_id", table_name="n8n_intake_items")
    op.drop_table("n8n_intake_items")
    op.drop_index("ix_n8n_intake_packages_lookup", table_name="n8n_intake_packages")
    op.drop_table("n8n_intake_packages")
