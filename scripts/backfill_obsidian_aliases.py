from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.document import Document
from app.models.legal_source_alias import LegalSourceAlias
from app.services.legal_source_alias_service import LegalSourceAliasService
from app.services.obsidian_ingestion_service import parse_frontmatter


@dataclass(frozen=True)
class ObsidianAliasBackfillRow:
    document_id: str
    workspace_id: str
    document_name: str
    file_path: str | None
    extracted_text: str | None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill legal_source_aliases from existing obsidian_markdown documents."
    )
    parser.add_argument("--workspace-id", help="Optional workspace filter.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum documents to process; 0 means no limit.")
    parser.add_argument("--commit-every", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.limit < 0:
        raise ValueError("--limit must be zero or positive")
    if args.commit_every <= 0:
        raise ValueError("--commit-every must be positive")

    settings = get_settings()
    engine = create_engine(str(settings.database_url), pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as db:
        result = backfill_obsidian_aliases(
            db,
            workspace_id=args.workspace_id,
            limit=args.limit,
            commit_every=args.commit_every,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


def backfill_obsidian_aliases(
    db: Session,
    *,
    workspace_id: str | None = None,
    limit: int = 0,
    commit_every: int = 100,
    dry_run: bool = False,
) -> dict[str, Any]:
    rows = fetch_obsidian_documents(db, workspace_id=workspace_id, limit=limit)
    service = LegalSourceAliasService(db)
    processed = 0
    alias_count = 0
    examples: list[dict[str, Any]] = []

    for row in rows:
        note_path = resolve_obsidian_note_path(row.file_path, row.document_name)
        frontmatter, _body = parse_frontmatter(row.extracted_text or "")
        title = str(frontmatter.get("title") or Path(note_path).stem or row.document_name)
        if dry_run:
            aliases = []
            from app.services.legal_source_alias_service import build_obsidian_aliases

            alias_values = build_obsidian_aliases(title=title, note_path=note_path, frontmatter=frontmatter)
            alias_count += len(alias_values)
            if len(examples) < 10:
                examples.append(
                    {
                        "document_id": row.document_id,
                        "note_path": note_path,
                        "aliases": alias_values,
                    }
                )
        else:
            aliases = service.sync_obsidian_document_aliases(
                workspace_id=row.workspace_id,
                document_id=row.document_id,
                title=title,
                note_path=note_path,
                frontmatter=frontmatter,
            )
            alias_count += len(aliases)
            if len(examples) < 10:
                examples.append(
                    {
                        "document_id": row.document_id,
                        "note_path": note_path,
                        "aliases": [alias.alias for alias in aliases],
                    }
                )
        processed += 1
        if not dry_run and processed % commit_every == 0:
            db.commit()

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return {
        "ok": True,
        "dry_run": dry_run,
        "documents_seen": len(rows),
        "documents_processed": processed,
        "aliases_written": 0 if dry_run else alias_count,
        "aliases_planned": alias_count if dry_run else None,
        "existing_alias_rows": count_alias_rows(db, workspace_id=workspace_id),
        "examples": examples,
    }


def fetch_obsidian_documents(
    db: Session,
    *,
    workspace_id: str | None = None,
    limit: int = 0,
) -> list[ObsidianAliasBackfillRow]:
    query = db.query(Document).filter(Document.document_type == "obsidian_markdown")
    if workspace_id:
        query = query.filter(Document.workspace_id == workspace_id)
    query = query.order_by(Document.created_at.asc(), Document.id.asc())
    if limit > 0:
        query = query.limit(limit)
    documents = query.all()
    return [
        ObsidianAliasBackfillRow(
            document_id=str(document.id),
            workspace_id=str(document.workspace_id),
            document_name=document.document_name,
            file_path=document.file_path,
            extracted_text=document.extracted_text,
        )
        for document in documents
    ]


def resolve_obsidian_note_path(file_path: str | None, document_name: str) -> str:
    if file_path and file_path.startswith("obsidian://"):
        return file_path.removeprefix("obsidian://")
    return document_name


def count_alias_rows(db: Session, *, workspace_id: str | None = None) -> int:
    query = db.query(LegalSourceAlias)
    if workspace_id:
        query = query.filter(LegalSourceAlias.workspace_id == workspace_id)
    return int(query.count())


if __name__ == "__main__":
    os.environ.setdefault("APP_ENV", "local")
    main()
