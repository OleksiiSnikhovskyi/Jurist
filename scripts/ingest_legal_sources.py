from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.document import Document
from app.models.legal_source import LegalSource
from app.repositories.document_repository import DocumentRepository
from app.services.chunking import split_text
from app.services.document_text_extractor import DocumentTextExtractor
from scripts.ingest_markdown_knowledge_base import (
    DEFAULT_USER_ID,
    DEFAULT_WORKSPACE_ID,
    ensure_workspace,
)


SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".txt", ".md"})


@dataclass(frozen=True)
class SourceManifestEntry:
    file_path: str
    source_name: str | None = None
    source_type: str | None = None
    source_url: str | None = None
    jurisdiction: str | None = None
    document_number: str | None = None
    adoption_date: date | None = None
    effective_date: date | None = None
    validity_status: str | None = None
    last_checked_at: datetime | None = None
    topic_tags: list[str] = field(default_factory=list)
    summary: str | None = None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest exported NotebookLM/legal-source files into jur_db."
    )
    parser.add_argument("paths", nargs="+", help="Legal source files or folders to ingest.")
    parser.add_argument("--manifest", help="Optional JSON or CSV manifest with source metadata.")
    parser.add_argument("--workspace-id", default=os.getenv("JUR_KB_WORKSPACE_ID", DEFAULT_WORKSPACE_ID))
    parser.add_argument("--workspace-name", default=os.getenv("JUR_KB_WORKSPACE_NAME", "JUR Legal Sources"))
    parser.add_argument("--user-id", default=os.getenv("JUR_KB_USER_ID", DEFAULT_USER_ID))
    parser.add_argument("--user-email", default=os.getenv("JUR_KB_USER_EMAIL", "jurist@example.local"))
    parser.add_argument("--user-name", default=os.getenv("JUR_KB_USER_NAME", "JUR Knowledge Curator"))
    parser.add_argument("--source-type", default="law")
    parser.add_argument("--jurisdiction", default="Ukraine")
    parser.add_argument("--validity-status", default="needs_verification")
    parser.add_argument("--chunk-size", type=int, default=1200)
    parser.add_argument("--overlap", type=int, default=150)
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
        result = ingest_legal_sources(
            db,
            paths=[Path(path) for path in args.paths],
            manifest_path=Path(args.manifest) if args.manifest else None,
            workspace_id=args.workspace_id,
            user_id=args.user_id,
            default_source_type=args.source_type,
            default_jurisdiction=args.jurisdiction,
            default_validity_status=args.validity_status,
            chunk_size=args.chunk_size,
            overlap=args.overlap,
        )
        db.commit()

    print(
        "legal_sources={sources} documents={documents} chunks={chunks} skipped={skipped}".format(
            sources=result["legal_sources"],
            documents=result["documents"],
            chunks=result["chunks"],
            skipped=result["skipped"],
        )
    )


def ingest_legal_sources(
    db: Session,
    *,
    paths: list[Path],
    manifest_path: Path | None,
    workspace_id: str,
    user_id: str,
    default_source_type: str,
    default_jurisdiction: str,
    default_validity_status: str,
    chunk_size: int = 1200,
    overlap: int = 150,
) -> dict[str, int]:
    manifest = load_manifest(manifest_path) if manifest_path else {}
    extractor = DocumentTextExtractor()
    repository = DocumentRepository(db)
    counts = {"legal_sources": 0, "documents": 0, "chunks": 0, "skipped": 0}

    for file_path in iter_source_files(paths):
        entry = manifest.get(_manifest_key(file_path)) or manifest.get(file_path.name)
        text = extract_source_text(file_path, extractor)
        if not text:
            counts["skipped"] += 1
            continue

        source = upsert_legal_source(
            db,
            file_path=file_path,
            text=text,
            entry=entry,
            default_source_type=default_source_type,
            default_jurisdiction=default_jurisdiction,
            default_validity_status=default_validity_status,
        )
        document = upsert_document(
            db,
            workspace_id=workspace_id,
            user_id=user_id,
            file_path=file_path,
            text=text,
            document_type=f"legal_source_{file_path.suffix.lower().lstrip('.')}",
        )
        repository.delete_chunks_for_document(document.id)
        chunks = split_text(text, chunk_size=chunk_size, overlap=overlap)
        repository.create_document_chunks(
            document_id=document.id,
            workspace_id=workspace_id,
            chunks=chunks,
        )
        counts["legal_sources"] += 1
        counts["documents"] += 1
        counts["chunks"] += len(chunks)
        db.add(source)

    return counts


def load_manifest(manifest_path: Path) -> dict[str, SourceManifestEntry]:
    if manifest_path.suffix.lower() == ".json":
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else raw.get("sources", [])
    elif manifest_path.suffix.lower() == ".csv":
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    else:
        raise ValueError("Manifest must be .json or .csv")

    manifest: dict[str, SourceManifestEntry] = {}
    for row in rows:
        entry = parse_manifest_entry(row)
        manifest[_manifest_key(Path(entry.file_path))] = entry
        manifest[Path(entry.file_path).name] = entry
    return manifest


def parse_manifest_entry(row: dict[str, Any]) -> SourceManifestEntry:
    file_path = str(row.get("file_path") or row.get("path") or row.get("filename") or "").strip()
    if not file_path:
        raise ValueError("Manifest row is missing file_path/path/filename")
    return SourceManifestEntry(
        file_path=file_path,
        source_name=_clean_optional(row.get("source_name") or row.get("title") or row.get("name")),
        source_type=_clean_optional(row.get("source_type")),
        source_url=_clean_optional(row.get("source_url") or row.get("url")),
        jurisdiction=_clean_optional(row.get("jurisdiction")),
        document_number=_clean_optional(row.get("document_number") or row.get("number")),
        adoption_date=parse_date(row.get("adoption_date")),
        effective_date=parse_date(row.get("effective_date")),
        validity_status=_clean_optional(row.get("validity_status") or row.get("status")),
        last_checked_at=parse_datetime(row.get("last_checked_at") or row.get("checked_at")),
        topic_tags=parse_tags(row.get("topic_tags") or row.get("tags")),
        summary=_clean_optional(row.get("summary")),
    )


def extract_source_text(file_path: Path, extractor: DocumentTextExtractor) -> str | None:
    suffix = file_path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return _normalize_text(file_path.read_text(encoding="utf-8"))
    return extractor.extract_text(file_path)


def upsert_legal_source(
    db: Session,
    *,
    file_path: Path,
    text: str,
    entry: SourceManifestEntry | None,
    default_source_type: str,
    default_jurisdiction: str,
    default_validity_status: str,
) -> LegalSource:
    source_name = entry.source_name if entry and entry.source_name else file_path.stem
    source_url = entry.source_url if entry else None
    document_number = entry.document_number if entry else None
    jurisdiction = entry.jurisdiction if entry and entry.jurisdiction else default_jurisdiction

    query = db.query(LegalSource).filter(LegalSource.source_name == source_name)
    if source_url:
        query = db.query(LegalSource).filter(LegalSource.source_url == source_url)
    elif document_number:
        query = query.filter(LegalSource.document_number == document_number)
    source = query.first()

    if source is None:
        source = LegalSource(source_name=source_name, source_type=default_source_type)
        db.add(source)
        db.flush()

    source.source_type = entry.source_type if entry and entry.source_type else default_source_type
    source.source_name = source_name
    source.source_url = source_url
    source.jurisdiction = jurisdiction
    source.document_number = document_number
    source.adoption_date = entry.adoption_date if entry else None
    source.effective_date = entry.effective_date if entry else None
    source.validity_status = (
        entry.validity_status if entry and entry.validity_status else default_validity_status
    )
    source.last_checked_at = (
        entry.last_checked_at if entry and entry.last_checked_at else datetime.now(UTC)
    )
    source.topic_tags = entry.topic_tags if entry and entry.topic_tags else []
    source.summary = entry.summary if entry else None
    source.full_text = text
    return source


def upsert_document(
    db: Session,
    *,
    workspace_id: str,
    user_id: str,
    file_path: Path,
    text: str,
    document_type: str,
) -> Document:
    source_path = file_path.resolve().as_posix()
    document = (
        db.query(Document)
        .filter(
            Document.workspace_id == workspace_id,
            Document.file_path == source_path,
        )
        .first()
    )
    if document is None:
        document = Document(
            workspace_id=workspace_id,
            uploaded_by=user_id,
            document_name=file_path.name,
            document_type=document_type,
            file_path=source_path,
            extracted_text=text,
            confidentiality_level="private",
        )
        db.add(document)
        db.flush()
        return document

    document.uploaded_by = user_id
    document.document_name = file_path.name
    document.document_type = document_type
    document.extracted_text = text
    db.add(document)
    db.flush()
    return document


def iter_source_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(
                child
                for child in sorted(path.rglob("*"))
                if child.is_file() and child.suffix.lower() in SUPPORTED_EXTENSIONS
            )
        elif path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(path)
    return sorted(set(files), key=lambda value: value.as_posix())


def parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for date_format in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value}")


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    parsed_date = parse_date(value)
    if not parsed_date:
        return None
    return datetime.combine(parsed_date, datetime.min.time(), tzinfo=UTC)


def parse_tags(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).replace(";", ",").split(",") if item.strip()]


def _manifest_key(file_path: Path) -> str:
    return file_path.as_posix()


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_text(value: str) -> str:
    lines = [line.rstrip() for line in value.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()


if __name__ == "__main__":
    main()
