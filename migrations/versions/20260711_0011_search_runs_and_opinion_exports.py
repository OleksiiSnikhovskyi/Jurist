"""Add search run and opinion export metadata.

Revision ID: 20260711_0011
Revises: 20260711_0010
Create Date: 2026-07-11
"""

import sqlalchemy as sa
from alembic import op

from app.models.types import GUID, JSONVariant

revision = "20260711_0011"
down_revision = "20260711_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "official_source_search_runs",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("workspace_id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("trigger_reason", sa.String(length=100), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("search_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allowed_domains", JSONVariant(), nullable=True),
        sa.Column("site_queries", JSONVariant(), nullable=True),
        sa.Column("accepted_urls", JSONVariant(), nullable=True),
        sa.Column("rejected_urls", JSONVariant(), nullable=True),
        sa.Column("metadata", JSONVariant(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_official_source_search_runs_workspace_created",
        "official_source_search_runs",
        ["workspace_id", "created_at"],
    )
    op.create_table(
        "legal_opinion_exports",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("legal_opinion_id", GUID(), nullable=False),
        sa.Column("workspace_id", GUID(), nullable=False),
        sa.Column("user_id", GUID(), nullable=False),
        sa.Column("exported_by", GUID(), nullable=False),
        sa.Column("export_format", sa.String(length=20), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("metadata", JSONVariant(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["legal_opinion_id"], ["legal_opinions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["exported_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_legal_opinion_exports_opinion_created",
        "legal_opinion_exports",
        ["legal_opinion_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_legal_opinion_exports_opinion_created", table_name="legal_opinion_exports")
    op.drop_table("legal_opinion_exports")
    op.drop_index(
        "ix_official_source_search_runs_workspace_created",
        table_name="official_source_search_runs",
    )
    op.drop_table("official_source_search_runs")
