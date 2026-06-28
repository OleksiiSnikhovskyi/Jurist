"""Add legal source validity metadata.

Revision ID: 20260628_0009
Revises: 20260628_0008
Create Date: 2026-06-28
"""

from alembic import op
import sqlalchemy as sa


revision = "20260628_0009"
down_revision = "20260628_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("legal_sources", sa.Column("revision_date", sa.Date(), nullable=True))
    op.add_column("legal_sources", sa.Column("validity_note", sa.Text(), nullable=True))
    op.create_index("ix_legal_sources_revision_date", "legal_sources", ["revision_date"])


def downgrade() -> None:
    op.drop_index("ix_legal_sources_revision_date", table_name="legal_sources")
    op.drop_column("legal_sources", "validity_note")
    op.drop_column("legal_sources", "revision_date")
