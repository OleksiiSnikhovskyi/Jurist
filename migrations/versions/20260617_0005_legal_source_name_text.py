"""Allow long official legal source names.

Revision ID: 20260617_0005
Revises: 20260614_0004
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa


revision = "20260617_0005"
down_revision = "20260614_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "legal_sources",
        "source_name",
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "legal_sources",
        "source_name",
        existing_type=sa.Text(),
        type_=sa.String(length=500),
        existing_nullable=False,
    )
