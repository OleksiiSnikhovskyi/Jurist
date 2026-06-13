from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.document import Document, DocumentChunk
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.access_control import AccessDeniedError
from app.services.embedding_service import serialize_embedding
from app.services.vector_search_service import (
    VectorSearchCommand,
    VectorSearchService,
    cosine_similarity,
)


class KeywordEmbeddingProvider:
    def embed(self, text: str) -> list[float]:
        normalized = text.lower()
        return [
            1.0 if "contract" in normalized else 0.0,
            1.0 if "tax" in normalized else 0.0,
            1.0 if "evidence" in normalized else 0.0,
        ]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    Workspace.__table__.create(engine)
    WorkspaceMember.__table__.create(engine)
    Document.__table__.create(engine)
    DocumentChunk.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _seed_chunks(db: Session) -> None:
    db.add(User(id="user-1", email="user@example.com", role="lawyer"))
    db.add(Workspace(id="workspace-1", name="Workspace", owner_id="user-1", workspace_type="case"))
    db.add(Workspace(id="workspace-2", name="Other", owner_id="user-1", workspace_type="case"))
    db.add(
        WorkspaceMember(
            id="member-1",
            workspace_id="workspace-1",
            user_id="user-1",
            role="viewer",
        )
    )
    db.add(
        Document(
            id="document-1",
            workspace_id="workspace-1",
            uploaded_by="user-1",
            document_name="contract.docx",
        )
    )
    db.add(
        Document(
            id="document-2",
            workspace_id="workspace-2",
            uploaded_by="user-1",
            document_name="tax.docx",
        )
    )
    db.add_all(
        [
            DocumentChunk(
                id="chunk-1",
                document_id="document-1",
                workspace_id="workspace-1",
                chunk_index=0,
                chunk_text="contract damages clause",
            ),
            DocumentChunk(
                id="chunk-2",
                document_id="document-1",
                workspace_id="workspace-1",
                chunk_index=1,
                chunk_text="evidence witness notes",
            ),
            DocumentChunk(
                id="chunk-3",
                document_id="document-2",
                workspace_id="workspace-2",
                chunk_index=0,
                chunk_text="tax private chunk",
            ),
        ]
    )
    db.commit()


def test_vector_search_filters_by_workspace_and_ranks_results(db_session: Session) -> None:
    _seed_chunks(db_session)

    results = VectorSearchService(
        db_session,
        embedding_provider=KeywordEmbeddingProvider(),
    ).search(
        VectorSearchCommand(
            workspace_id="workspace-1",
            user_id="user-1",
            query="contract",
            limit=10,
        )
    )

    assert [result.chunk_id for result in results] == ["chunk-1", "chunk-2"]
    assert all(result.workspace_id == "workspace-1" for result in results)
    assert "tax private chunk" not in [result.chunk_text for result in results]
    assert results[0].score > results[1].score


def test_vector_search_persists_missing_chunk_embeddings(db_session: Session) -> None:
    _seed_chunks(db_session)

    VectorSearchService(db_session, embedding_provider=KeywordEmbeddingProvider()).search(
        VectorSearchCommand(workspace_id="workspace-1", user_id="user-1", query="contract")
    )

    chunks = db_session.query(DocumentChunk).filter_by(workspace_id="workspace-1").all()
    assert all(chunk.embedding for chunk in chunks)


def test_vector_search_uses_existing_embedding(db_session: Session) -> None:
    _seed_chunks(db_session)
    chunk = db_session.get(DocumentChunk, "chunk-2")
    assert chunk is not None
    chunk.embedding = serialize_embedding([0.0, 0.0, 1.0])
    db_session.commit()

    results = VectorSearchService(db_session, embedding_provider=KeywordEmbeddingProvider()).search(
        VectorSearchCommand(workspace_id="workspace-1", user_id="user-1", query="evidence")
    )

    assert results[0].chunk_id == "chunk-2"


def test_vector_search_denies_non_member(db_session: Session) -> None:
    _seed_chunks(db_session)

    with pytest.raises(AccessDeniedError):
        VectorSearchService(db_session, embedding_provider=KeywordEmbeddingProvider()).search(
            VectorSearchCommand(workspace_id="workspace-2", user_id="user-1", query="tax")
        )


def test_cosine_similarity_rejects_dimension_mismatch() -> None:
    with pytest.raises(ValueError):
        cosine_similarity([1.0], [1.0, 0.0])
