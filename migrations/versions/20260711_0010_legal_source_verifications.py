"""Add legal source verification metadata.

Revision ID: 20260711_0010
Revises: 20260628_0009
Create Date: 2026-07-11
"""

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, JSONVariant

revision = "20260711_0010"
down_revision = "20260628_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legal_source_verifications",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("legal_source_id", GUID(), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("source_domain", sa.String(length=255), nullable=True),
        sa.Column(
            "source_kind",
            sa.String(length=100),
            nullable=False,
            server_default="legislation",
        ),
        sa.Column("allowlist_status", sa.String(length=50), nullable=False),
        sa.Column("verification_status", sa.String(length=100), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("final_url", sa.String(length=1000), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("confidence", sa.String(length=50), nullable=False, server_default="medium"),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_by", sa.String(length=100), nullable=False, server_default="n8n"),
        sa.Column("evidence_summary", sa.Text(), nullable=True),
        sa.Column("verification_payload", JSONVariant(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["legal_source_id"], ["legal_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "legal_source_id",
            "source_url",
            name="uq_legal_source_verifications_source",
        ),
    )
    op.create_index(
        "ix_legal_source_verifications_status",
        "legal_source_verifications",
        ["verification_status", "checked_at"],
    )
    op.create_index(
        "ix_legal_source_verifications_domain",
        "legal_source_verifications",
        ["source_domain"],
    )


def downgrade() -> None:
    op.drop_index("ix_legal_source_verifications_domain", table_name="legal_source_verifications")
    op.drop_index("ix_legal_source_verifications_status", table_name="legal_source_verifications")
    op.drop_table("legal_source_verifications")


