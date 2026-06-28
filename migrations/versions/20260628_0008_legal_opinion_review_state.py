"""Add review state to legal opinions.

Revision ID: 20260628_0008
Revises: 20260626_0007
Create Date: 2026-06-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260628_0008"
down_revision = "20260626_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "legal_opinions",
        sa.Column("review_status", sa.String(length=50), nullable=False, server_default="draft"),
    )
    op.add_column(
        "legal_opinions",
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column("legal_opinions", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("legal_opinions", sa.Column("review_notes", sa.Text(), nullable=True))
    op.add_column(
        "legal_opinions",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_legal_opinions_workspace_review_status",
        "legal_opinions",
        ["workspace_id", "review_status"],
    )
    op.create_index("ix_legal_opinions_reviewed_by", "legal_opinions", ["reviewed_by"])


def downgrade() -> None:
    op.drop_index("ix_legal_opinions_reviewed_by", table_name="legal_opinions")
    op.drop_index("ix_legal_opinions_workspace_review_status", table_name="legal_opinions")
    op.drop_column("legal_opinions", "updated_at")
    op.drop_column("legal_opinions", "review_notes")
    op.drop_column("legal_opinions", "reviewed_at")
    op.drop_column("legal_opinions", "reviewed_by")
    op.drop_column("legal_opinions", "review_status")
