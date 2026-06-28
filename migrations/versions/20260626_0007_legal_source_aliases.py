"""Add legal source aliases registry.

Revision ID: 20260626_0007
Revises: 20260620_0006
Create Date: 2026-06-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260626_0007"
down_revision = "20260620_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legal_source_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("workspaces.id"), nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("documents.id"), nullable=True),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("normalized_alias", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=True),
        sa.Column("document_number", sa.String(length=100), nullable=True),
        sa.Column("source_url", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_legal_source_aliases_workspace_normalized",
        "legal_source_aliases",
        ["workspace_id", "normalized_alias"],
    )
    op.create_index(
        "ix_legal_source_aliases_normalized",
        "legal_source_aliases",
        ["normalized_alias"],
    )
    op.create_index(
        "ix_legal_source_aliases_document_id",
        "legal_source_aliases",
        ["document_id"],
    )
    op.create_index(
        "ix_legal_source_aliases_document_number",
        "legal_source_aliases",
        ["document_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_legal_source_aliases_document_number", table_name="legal_source_aliases")
    op.drop_index("ix_legal_source_aliases_document_id", table_name="legal_source_aliases")
    op.drop_index("ix_legal_source_aliases_normalized", table_name="legal_source_aliases")
    op.drop_index("ix_legal_source_aliases_workspace_normalized", table_name="legal_source_aliases")
    op.drop_table("legal_source_aliases")
