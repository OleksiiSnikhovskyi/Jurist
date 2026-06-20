"""Switch document chunk embeddings to bge-m3 dimensions.

Revision ID: 20260620_0006
Revises: 20260617_0005
Create Date: 2026-06-20
"""

from alembic import op


revision = "20260620_0006"
down_revision = "20260617_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1024) USING NULL")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_workspace_id "
        "ON document_chunks (workspace_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_document_id_chunk_index "
        "ON document_chunks (document_id, chunk_index)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_workspace_type "
        "ON documents (workspace_id, document_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_legal_sources_document_number "
        "ON legal_sources (document_number)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_legal_sources_validity_source_type "
        "ON legal_sources (validity_status, source_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_legal_sources_source_name_trgm "
        "ON legal_sources USING gin (source_name gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_legal_sources_source_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_legal_sources_validity_source_type")
    op.execute("DROP INDEX IF EXISTS ix_legal_sources_document_number")
    op.execute("DROP INDEX IF EXISTS ix_documents_workspace_type")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_document_id_chunk_index")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_workspace_id")
    op.execute("ALTER TABLE document_chunks ALTER COLUMN embedding TYPE vector(1536) USING NULL")
