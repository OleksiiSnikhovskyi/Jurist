from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.document import DocumentChunk
from app.services.embedding_service import get_embedding_provider, serialize_embedding


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill document_chunks.embedding with the configured embedding provider."
    )
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--limit", type=int, default=0, help="Maximum chunks to process; 0 means no limit.")
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--state", default="legal_sources/reembed_state.json")
    args = parser.parse_args()

    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")

    settings = get_settings()
    provider = get_embedding_provider(settings)
    engine = create_engine(str(settings.database_url), pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    state_path = Path(args.state)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    processed = 0
    with SessionLocal() as db:
        dialect_name = db.get_bind().dialect.name
        while args.limit <= 0 or processed < args.limit:
            remaining = args.batch_size if args.limit <= 0 else min(args.batch_size, args.limit - processed)
            chunks = fetch_null_embedding_chunks(db, dialect_name=dialect_name, limit=remaining)
            if not chunks:
                write_state(
                    state_path,
                    {
                        "ok": True,
                        "finished": True,
                        "processed": processed,
                        "embedding_provider": settings.embedding_provider,
                        "embedding_model": settings.embedding_model,
                        "embedding_dimensions": settings.embedding_dimensions,
                    },
                )
                print(json.dumps(read_state(state_path), ensure_ascii=False, indent=2))
                return

            embeddings = provider.embed_batch([chunk["chunk_text"] for chunk in chunks])
            if any(len(embedding) != settings.embedding_dimensions for embedding in embeddings):
                raise RuntimeError("Embedding provider returned an unexpected vector size")

            for chunk, embedding in zip(chunks, embeddings, strict=True):
                persist_embedding(
                    db,
                    dialect_name=dialect_name,
                    chunk_id=chunk["id"],
                    embedding=serialize_embedding(embedding),
                )
            db.commit()
            processed += len(chunks)
            write_state(
                state_path,
                {
                    "ok": True,
                    "finished": False,
                    "processed": processed,
                    "last_chunk_id": chunks[-1]["id"],
                    "updated_at": datetime.now(UTC).isoformat(),
                    "embedding_provider": settings.embedding_provider,
                    "embedding_model": settings.embedding_model,
                    "embedding_dimensions": settings.embedding_dimensions,
                },
            )
            print(json.dumps(read_state(state_path), ensure_ascii=False), flush=True)
            if args.sleep_seconds > 0:
                time.sleep(args.sleep_seconds)


def fetch_null_embedding_chunks(db: Any, *, dialect_name: str, limit: int) -> list[dict[str, str]]:
    if dialect_name == "postgresql":
        rows = db.execute(
            text(
                """
                SELECT id::text AS id, chunk_text
                FROM document_chunks
                WHERE embedding IS NULL
                  AND length(trim(chunk_text)) > 0
                ORDER BY created_at ASC, chunk_index ASC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings()
        return [{"id": str(row["id"]), "chunk_text": str(row["chunk_text"])} for row in rows]

    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.embedding.is_(None), DocumentChunk.chunk_text != "")
        .order_by(DocumentChunk.created_at.asc(), DocumentChunk.chunk_index.asc())
        .limit(limit)
        .all()
    )
    return [{"id": str(row.id), "chunk_text": row.chunk_text} for row in rows]


def persist_embedding(db: Any, *, dialect_name: str, chunk_id: str, embedding: str) -> None:
    if dialect_name == "postgresql":
        db.execute(
            text("UPDATE document_chunks SET embedding = CAST(:embedding AS vector) WHERE id = :chunk_id"),
            {"embedding": embedding, "chunk_id": chunk_id},
        )
        return

    chunk = db.get(DocumentChunk, chunk_id)
    if chunk is not None:
        chunk.embedding = embedding
        db.add(chunk)


def write_state(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    os.environ.setdefault("APP_ENV", "local")
    main()
