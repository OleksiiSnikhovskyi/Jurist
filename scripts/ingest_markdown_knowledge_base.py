from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.document import Document
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.repositories.document_repository import DocumentRepository
from app.services.chunking import split_text
from app.services.obsidian_ingestion_service import ObsidianIngestionService


DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000101"


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Markdown files into the legal assistant KB.")
    parser.add_argument("paths", nargs="+", help="Markdown files or folders to ingest.")
    parser.add_argument("--workspace-id", default=os.getenv("JUR_KB_WORKSPACE_ID", DEFAULT_WORKSPACE_ID))
    parser.add_argument("--workspace-name", default=os.getenv("JUR_KB_WORKSPACE_NAME", "JUR Knowledge Base"))
    parser.add_argument("--user-id", default=os.getenv("JUR_KB_USER_ID", DEFAULT_USER_ID))
    parser.add_argument("--user-email", default=os.getenv("JUR_KB_USER_EMAIL", "jurist@example.local"))
    parser.add_argument("--user-name", default=os.getenv("JUR_KB_USER_NAME", "JUR Knowledge Curator"))
    parser.add_argument("--document-type", default="knowledge_markdown")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(str(settings.database_url))
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        ensure_workspace(
            db,
            user_id=args.user_id,
            user_email=args.user_email,
            user_name=args.user_name,
            workspace_id=args.workspace_id,
            workspace_name=args.workspace_name,
        )
        result = ingest_paths(
            db,
            paths=[Path(path) for path in args.paths],
            workspace_id=args.workspace_id,
            user_id=args.user_id,
            document_type=args.document_type,
        )
        db.commit()

    print(
        "ingested={ingested} chunks={chunks} workspace_id={workspace_id} user_id={user_id}".format(
            ingested=result["documents"],
            chunks=result["chunks"],
            workspace_id=args.workspace_id,
            user_id=args.user_id,
        )
    )


def ensure_workspace(
    db: Session,
    *,
    user_id: str,
    user_email: str,
    user_name: str,
    workspace_id: str,
    workspace_name: str,
) -> None:
    user = db.get(User, user_id)
    if user is None:
        user = User(id=user_id, email=user_email, full_name=user_name, role="lawyer")
        db.add(user)
        db.flush()

    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        workspace = Workspace(
            id=workspace_id,
            name=workspace_name,
            owner_id=user_id,
            workspace_type="knowledge_base",
        )
        db.add(workspace)
        db.flush()

    membership = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        .first()
    )
    if membership is None:
        db.add(
            WorkspaceMember(
                workspace_id=workspace_id,
                user_id=user_id,
                role="lawyer",
            )
        )
        db.flush()


def ingest_paths(
    db: Session,
    *,
    paths: list[Path],
    workspace_id: str,
    user_id: str,
    document_type: str,
) -> dict[str, int]:
    markdown_files = list(_iter_markdown_files(paths))
    repository = DocumentRepository(db)
    obsidian = ObsidianIngestionService()
    document_count = 0
    chunk_count = 0

    for markdown_file in markdown_files:
        note = obsidian.parse_note(markdown_file, markdown_file.parent)
        source_path = markdown_file.as_posix()
        document = _upsert_document(
            db,
            workspace_id=workspace_id,
            user_id=user_id,
            document_name=note.path,
            document_type=document_type,
            file_path=source_path,
            extracted_text=note.body,
        )
        repository.delete_chunks_for_document(document.id)
        chunks = split_text(note.body, chunk_size=1200, overlap=150)
        repository.create_document_chunks(
            document_id=document.id,
            workspace_id=workspace_id,
            chunks=chunks,
        )
        document_count += 1
        chunk_count += len(chunks)

    return {"documents": document_count, "chunks": chunk_count}


def _upsert_document(
    db: Session,
    *,
    workspace_id: str,
    user_id: str,
    document_name: str,
    document_type: str,
    file_path: str,
    extracted_text: str,
) -> Document:
    document = (
        db.query(Document)
        .filter(
            Document.workspace_id == workspace_id,
            Document.file_path == file_path,
        )
        .first()
    )
    if document is None:
        document = Document(
            workspace_id=workspace_id,
            uploaded_by=user_id,
            document_name=document_name,
            document_type=document_type,
            file_path=file_path,
            extracted_text=extracted_text,
            confidentiality_level="private",
        )
        db.add(document)
        db.flush()
        return document

    document.document_name = document_name
    document.document_type = document_type
    document.uploaded_by = user_id
    document.extracted_text = extracted_text
    db.add(document)
    db.flush()
    return document


def _iter_markdown_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(
                child
                for child in sorted(path.rglob("*.md"))
                if ".obsidian" not in child.parts
            )
        elif path.is_file() and path.suffix.lower() == ".md":
            files.append(path)
    return sorted(set(files), key=lambda value: value.as_posix())


if __name__ == "__main__":
    main()
