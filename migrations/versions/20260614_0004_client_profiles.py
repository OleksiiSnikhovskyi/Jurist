"""Add workspace client profiles.

Revision ID: 20260614_0004
Revises: 20260614_0003
Create Date: 2026-06-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260614_0004"
down_revision = "20260614_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("client_type", sa.String(length=100), nullable=True),
        sa.Column("matter_role", sa.String(length=255), nullable=True),
        sa.Column("interests", sa.Text(), nullable=True),
        sa.Column("risk_preferences", sa.Text(), nullable=True),
        sa.Column("communication_preferences", sa.Text(), nullable=True),
        sa.Column("factual_context", sa.Text(), nullable=True),
        sa.Column("extra_context", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_client_profiles_workspace_id", "client_profiles", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_client_profiles_workspace_id", table_name="client_profiles")
    op.drop_table("client_profiles")
