from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.audit_log import AuditLog
from app.models.document import Document, DocumentChunk
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.access_control import AccessDeniedError
from app.services.document_chunking_service import (
    DocumentChunkingCommand,
    DocumentChunkingService,
    DocumentHasNoExtractedTextError,
)


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
    AuditLog.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _seed_document(db: Session, *, extracted_text: str | None = None) -> None:
    db.add(User(id="user-1", email="user@example.com", role="lawyer"))
    db.add(Workspace(id="workspace-1", name="Workspace", owner_id="user-1", workspace_type="case"))
    db.add(Workspace(id="workspace-2", name="Other", owner_id="user-1", workspace_type="case"))
    db.add(
        WorkspaceMember(
            id="member-1",
            workspace_id="workspace-1",
            user_id="user-1",
            role="lawyer",
        )
    )
    db.add(
        Document(
            id="document-1",
            workspace_id="workspace-1",
            uploaded_by="user-1",
            document_name="contract.docx",
            extracted_text=extracted_text,
        )
    )
    db.add(
        Document(
            id="document-2",
            workspace_id="workspace-2",
            uploaded_by="user-1",
            document_name="other.docx",
            extracted_text="Other workspace text",
        )
    )
    db.commit()


def test_persist_chunks_from_extracted_text(db_session: Session) -> None:
    _seed_document(db_session, extracted_text="alpha beta gamma " * 20)

    chunks = DocumentChunkingService(db_session).persist_chunks(
        DocumentChunkingCommand(
            document_id="document-1",
            workspace_id="workspace-1",
            user_id="user-1",
            chunk_size=40,
            overlap=5,
        )
    )

    audit_log = db_session.query(AuditLog).one()
    assert len(chunks) > 1
    assert all(chunk.workspace_id == "workspace-1" for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert audit_log.action == "document.chunked"
    assert audit_log.metadata_json == {"chunk_count": len(chunks)}


def test_persist_chunks_replaces_existing_chunks(db_session: Session) -> None:
    _seed_document(db_session, extracted_text="alpha beta gamma " * 20)
    service = DocumentChunkingService(db_session)

    first_run = service.persist_chunks(
        DocumentChunkingCommand(
            document_id="document-1",
            workspace_id="workspace-1",
            user_id="user-1",
            chunk_size=40,
            overlap=5,
        )
    )
    second_run = service.persist_chunks(
        DocumentChunkingCommand(
            document_id="document-1",
            workspace_id="workspace-1",
            user_id="user-1",
            chunk_size=80,
            overlap=5,
        )
    )

    stored_chunks = db_session.query(DocumentChunk).filter_by(document_id="document-1").all()
    assert len(second_run) < len(first_run)
    assert len(stored_chunks) == len(second_run)


def test_persist_chunks_denies_cross_workspace_document(db_session: Session) -> None:
    _seed_document(db_session, extracted_text="alpha beta gamma")

    with pytest.raises(AccessDeniedError, match="Document does not belong"):
        DocumentChunkingService(db_session).persist_chunks(
            DocumentChunkingCommand(
                document_id="document-2",
                workspace_id="workspace-1",
                user_id="user-1",
            )
        )


def test_persist_chunks_requires_extracted_text(db_session: Session) -> None:
    _seed_document(db_session, extracted_text=None)

    with pytest.raises(DocumentHasNoExtractedTextError):
        DocumentChunkingService(db_session).persist_chunks(
            DocumentChunkingCommand(
                document_id="document-1",
                workspace_id="workspace-1",
                user_id="user-1",
            )
        )
