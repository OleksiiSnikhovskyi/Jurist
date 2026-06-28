from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.document import Document
from app.models.legal_source_alias import LegalSourceAlias
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from scripts.backfill_obsidian_aliases import (
    backfill_obsidian_aliases,
    resolve_obsidian_note_path,
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
    LegalSourceAlias.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_backfill_obsidian_aliases_writes_alias_rows(db_session: Session) -> None:
    _seed_workspace(db_session)
    db_session.add(
        Document(
            id="document-1",
            workspace_id="workspace-1",
            uploaded_by="user-1",
            document_name="cases/dbn-note.md",
            document_type="obsidian_markdown",
            file_path="obsidian://cases/dbn-note.md",
            extracted_text="""---
title: ДБН А.2.2-14:2016
aliases: [ДБН проектна документація, DBN A.2.2-14]
document_number: ДБН А.2.2-14:2016
source_name: ДБН А.2.2-14:2016
---
Текст нотатки.
""",
        )
    )
    db_session.commit()

    result = backfill_obsidian_aliases(db_session)

    assert result["documents_processed"] == 1
    assert result["aliases_written"] == 4
    aliases = db_session.query(LegalSourceAlias).filter_by(document_id="document-1").all()
    assert {alias.normalized_alias for alias in aliases} == {
        "дбн а.2.2-14:2016",
        "dbn-note",
        "дбн проектна документація",
        "dbn a.2.2-14",
    }


def test_backfill_obsidian_aliases_dry_run_does_not_write(db_session: Session) -> None:
    _seed_workspace(db_session)
    db_session.add(
        Document(
            id="document-1",
            workspace_id="workspace-1",
            uploaded_by="user-1",
            document_name="note.md",
            document_type="obsidian_markdown",
            extracted_text="Plain note body.",
        )
    )
    db_session.commit()

    result = backfill_obsidian_aliases(db_session, dry_run=True)

    assert result["documents_processed"] == 1
    assert result["aliases_written"] == 0
    assert result["aliases_planned"] == 1
    assert db_session.query(LegalSourceAlias).count() == 0


def test_resolve_obsidian_note_path_prefers_obsidian_uri() -> None:
    assert resolve_obsidian_note_path("obsidian://folder/note.md", "fallback.md") == "folder/note.md"
    assert resolve_obsidian_note_path(None, "fallback.md") == "fallback.md"


def _seed_workspace(db: Session) -> None:
    db.add(User(id="user-1", email="user@example.com", role="lawyer"))
    db.add(Workspace(id="workspace-1", name="Workspace", owner_id="user-1", workspace_type="case"))
    db.add(WorkspaceMember(id="member-1", workspace_id="workspace-1", user_id="user-1", role="lawyer"))
    db.commit()
