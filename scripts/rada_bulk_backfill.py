from __future__ import annotations

import argparse
import csv
import functools
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.prepare_priority_legal_source_manifest import OUTPUT_FIELDS, prepare_manifest_rows
from scripts.rada_catalog_sync import (
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_USER_AGENT,
    download_manifest_documents,
    parse_rada_arrivals_html,
    read_input,
)

DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000101"

RADA_FULL_CATALOG_PAGE_URL = "https://zakon.rada.gov.ua/laws/main/a/page"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BulkBackfillState:
    next_offset: int = 1
    catalog_pages: int = 0
    manifest_rows: int = 0
    downloaded: int = 0
    skipped_downloads: int = 0
    failed_downloads: int = 0
    ingested_sources: int = 0
    ingested_documents: int = 0
    ingested_chunks: int = 0
    skipped_ingest: int = 0
    updated_at: str | None = None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill the official Rada legislation catalog into PostgreSQL with resume state."
        )
    )
    parser.add_argument("--catalog-url", default=RADA_FULL_CATALOG_PAGE_URL)
    parser.add_argument("--documents-dir", default="legal_sources")
    parser.add_argument("--manifest", default="legal_sources/rada_bulk_manifest.csv")
    parser.add_argument("--state", default="legal_sources/rada_bulk_state.json")
    parser.add_argument("--workspace-id", default=os.getenv("JUR_KB_WORKSPACE_ID", DEFAULT_WORKSPACE_ID))
    parser.add_argument("--workspace-name", default=os.getenv("JUR_KB_WORKSPACE_NAME", "JUR Legal Sources"))
    parser.add_argument("--user-id", default=os.getenv("JUR_KB_USER_ID", DEFAULT_USER_ID))
    parser.add_argument("--user-email", default=os.getenv("JUR_KB_USER_EMAIL", "jurist@example.local"))
    parser.add_argument("--user-name", default=os.getenv("JUR_KB_USER_NAME", "JUR Knowledge Curator"))
    parser.add_argument(
        "--page-size",
        type=int,
        default=1,
        help="Rada catalog page increment. zakon.rada.gov.ua uses sequential page numbers.",
    )
    parser.add_argument("--limit-pages", type=int)
    parser.add_argument("--limit-documents", type=int)
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    parser.add_argument("--catalog-retries", type=int, default=3)
    parser.add_argument("--catalog-retry-seconds", type=float, default=10.0)
    parser.add_argument("--catalog-jitter-seconds", type=float, default=0.0)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--request-timeout", type=float, default=DEFAULT_REQUEST_TIMEOUT)
    parser.add_argument("--chunk-size", type=int, default=1200)
    parser.add_argument("--overlap", type=int, default=150)
    parser.add_argument(
        "--include-non-current",
        action="store_true",
        help="Include obsolete, pending, and needs_verification rows. By default only current rows are ingested.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-forbidden-pages",
        action="store_true",
        help="If a catalog page returns 403 Forbidden, record it and skip instead of stopping.",
    )
    parser.add_argument(
        "--failure-log",
        default="legal_sources/rada_catalog_failures.log",
        help="JSON-lines log of forbidden/failed catalog pages.",
    )
    parser.add_argument(
        "--catalog-page-url-style",
        choices=["auto", "slash", "no-slash"],
        default="auto",
        help="URL pagination style: auto (default behavior), slash (always /page/N/), no-slash (always /pageN).",
    )
    args = parser.parse_args()

    result = run_backfill(
        catalog_url=args.catalog_url,
        documents_dir=Path(args.documents_dir),
        manifest_path=Path(args.manifest),
        state_path=Path(args.state),
        workspace_id=args.workspace_id,
        workspace_name=args.workspace_name,
        user_id=args.user_id,
        user_email=args.user_email,
        user_name=args.user_name,
        page_size=args.page_size,
        limit_pages=args.limit_pages,
        limit_documents=args.limit_documents,
        sleep_seconds=args.sleep_seconds,
        catalog_retries=args.catalog_retries,
        catalog_retry_seconds=args.catalog_retry_seconds,
        catalog_jitter_seconds=args.catalog_jitter_seconds,
        user_agent=args.user_agent,
        request_timeout=args.request_timeout,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        current_only=not args.include_non_current,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
        skip_forbidden_pages=args.skip_forbidden_pages,
        failure_log_path=Path(args.failure_log),
        url_style=args.catalog_page_url_style,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def run_backfill(
    *,
    catalog_url: str,
    documents_dir: Path,
    manifest_path: Path,
    state_path: Path,
    workspace_id: str,
    workspace_name: str,
    user_id: str,
    user_email: str,
    user_name: str,
    page_size: int = 1,
    limit_pages: int | None = None,
    limit_documents: int | None = None,
    sleep_seconds: float = 0.5,
    catalog_retries: int = 3,
    catalog_retry_seconds: float = 10.0,
    catalog_jitter_seconds: float = 0.0,
    user_agent: str = DEFAULT_USER_AGENT,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    chunk_size: int = 1200,
    overlap: int = 150,
    current_only: bool = False,
    overwrite: bool = False,
    dry_run: bool = False,
    skip_forbidden_pages: bool = False,
    failure_log_path: Path | None = None,
    url_style: str = "auto",
    fetcher: Any = read_input,
) -> dict[str, int | str | bool | None]:
    state = load_state(state_path)
    page_count = 0
    accepted_documents = 0
    checked_at = datetime.now(UTC).date().isoformat()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    documents_dir.mkdir(parents=True, exist_ok=True)
    if failure_log_path is None:
        failure_log_path = manifest_path.parent / "rada_catalog_failures.log"
    failure_log_path.parent.mkdir(parents=True, exist_ok=True)
    stopped_reason = None

    if fetcher is read_input:
        fetcher = functools.partial(
            read_input, user_agent=user_agent, timeout=request_timeout
        )

    SessionLocal = None
    if not dry_run:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.config import get_settings

        settings = get_settings()
        engine = create_engine(str(settings.database_url))
        SessionLocal = sessionmaker(bind=engine)

    while True:
        if limit_pages is not None and page_count >= limit_pages:
            break
        if limit_documents is not None and accepted_documents >= limit_documents:
            break

        page_url = build_catalog_page_url(catalog_url, state.next_offset, url_style=url_style)
        try:
            html = fetch_catalog_page_with_retries(
                page_url,
                fetcher=fetcher,
                retries=catalog_retries,
                retry_seconds=catalog_retry_seconds,
                jitter_seconds=catalog_jitter_seconds,
            )
        except HTTPError as exc:
            if exc.code == 403 and skip_forbidden_pages:
                logger.warning(f"Catalog page {state.next_offset} ({page_url}) returned 403 Forbidden, recording and skipping.")
                _record_failed_page(failure_log_path, state.next_offset, page_url, 403, str(exc))
                state = save_progress(state, state_path, next_offset=state.next_offset + page_size)
                page_count += 1
                time.sleep(max(0.0, sleep_seconds))
                continue
            stopped_reason = f"catalog_fetch_failed:{type(exc).__name__}:HTTP {exc.code}"
            break
        except Exception as exc:
            stopped_reason = f"catalog_fetch_failed:{type(exc).__name__}:{exc}"
            break
        rows = parse_rada_arrivals_html(html, checked_at=checked_at)
        if not rows:
            break

        prepared, _issues = prepare_manifest_rows(rows, today=checked_at, allow_issues=True)
        prepared = filter_manifest_rows(prepared, current_only=current_only)
        if limit_documents is not None:
            prepared = prepared[: max(0, limit_documents - accepted_documents)]
        if not prepared:
            state = save_progress(state, state_path, next_offset=state.next_offset + page_size)
            page_count += 1
            time.sleep(max(0.0, sleep_seconds))
            continue

        append_manifest_rows(manifest_path, prepared)
        download_counts = {"downloaded": 0, "skipped": 0, "failed": 0}
        ingest_counts = {"legal_sources": 0, "documents": 0, "chunks": 0, "skipped": 0}
        if not dry_run:
            from scripts.ingest_legal_sources import ingest_legal_sources
            from scripts.ingest_markdown_knowledge_base import ensure_workspace

            download_counts = download_manifest_documents(
                prepared,
                documents_dir=documents_dir,
                overwrite=overwrite,
                fetcher=fetcher,
            )
            page_manifest = write_page_manifest(
                manifest_path.parent,
                state.next_offset,
                prepared,
            )
            with SessionLocal() as db:
                ensure_workspace(
                    db,
                    user_id=user_id,
                    user_email=user_email,
                    user_name=user_name,
                    workspace_id=workspace_id,
                    workspace_name=workspace_name,
                )
                ingest_counts = ingest_legal_sources(
                    db,
                    paths=[
                        documents_dir / row["file_path"]
                        for row in prepared
                        if row.get("file_path")
                    ],
                    manifest_path=page_manifest,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    default_source_type="law",
                    default_jurisdiction="Ukraine",
                    default_validity_status="needs_verification",
                    chunk_size=chunk_size,
                    overlap=overlap,
                )
                db.commit()

        accepted_documents += len(prepared)
        page_count += 1
        state = save_progress(
            state,
            state_path,
            next_offset=state.next_offset + page_size,
            catalog_pages=state.catalog_pages + 1,
            manifest_rows=state.manifest_rows + len(prepared),
            downloaded=state.downloaded + download_counts["downloaded"],
            skipped_downloads=state.skipped_downloads + download_counts["skipped"],
            failed_downloads=state.failed_downloads + download_counts["failed"],
            ingested_sources=state.ingested_sources + ingest_counts["legal_sources"],
            ingested_documents=state.ingested_documents + ingest_counts["documents"],
            ingested_chunks=state.ingested_chunks + ingest_counts["chunks"],
            skipped_ingest=state.skipped_ingest + ingest_counts["skipped"],
        )
        time.sleep(max(0.0, sleep_seconds))

    return {
        "ok": stopped_reason is None,
        "dry_run": dry_run,
        "pages_this_run": page_count,
        "documents_this_run": accepted_documents,
        "stopped_reason": stopped_reason,
        "next_offset": state.next_offset,
        "catalog_pages_total": state.catalog_pages,
        "manifest_rows_total": state.manifest_rows,
        "downloaded_total": state.downloaded,
        "failed_downloads_total": state.failed_downloads,
        "ingested_documents_total": state.ingested_documents,
        "ingested_chunks_total": state.ingested_chunks,
    }


def build_catalog_page_url(catalog_url: str, offset: int, url_style: str = "auto") -> str:
    clean_url = catalog_url.rstrip("/")
    if offset <= 1:
        return clean_url

    if url_style == "slash":
        return f"{clean_url}/{offset}/"
    if url_style == "no-slash":
        return f"{clean_url}{offset}"
    if url_style == "auto":
        if offset >= 1000:
            return f"{clean_url}{offset}/"
        return f"{clean_url}{offset}"

    raise ValueError(f"Unknown url_style: {url_style}")


def fetch_catalog_page_with_retries(
    page_url: str,
    *,
    fetcher: Any,
    retries: int,
    retry_seconds: float,
    jitter_seconds: float = 0.0,
) -> str:
    attempts = max(1, retries + 1)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return fetcher(page_url)
        except Exception as exc:
            last_error = exc
            if attempt >= attempts - 1:
                break
            delay = retry_seconds * (2 ** attempt) + random.uniform(0, jitter_seconds)
            delay = min(delay, retry_seconds * 10)
            time.sleep(max(0.0, delay))
    assert last_error is not None
    raise last_error


def filter_manifest_rows(rows: list[dict[str, str]], *, current_only: bool) -> list[dict[str, str]]:
    if not current_only:
        return rows
    return [row for row in rows if row.get("validity_status") == "current"]


def append_manifest_rows(path: Path, rows: list[dict[str, str]]) -> None:
    file_exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def write_page_manifest(root: Path, offset: int, rows: list[dict[str, str]]) -> Path:
    page_manifest = root / "rada_bulk_pages" / f"page_{offset}.csv"
    page_manifest.parent.mkdir(parents=True, exist_ok=True)
    with page_manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return page_manifest


def load_state(path: Path) -> BulkBackfillState:
    if not path.exists():
        return BulkBackfillState()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return BulkBackfillState(
        next_offset=int(raw.get("next_offset") or 1),
        catalog_pages=int(raw.get("catalog_pages") or 0),
        manifest_rows=int(raw.get("manifest_rows") or 0),
        downloaded=int(raw.get("downloaded") or 0),
        skipped_downloads=int(raw.get("skipped_downloads") or 0),
        failed_downloads=int(raw.get("failed_downloads") or 0),
        ingested_sources=int(raw.get("ingested_sources") or 0),
        ingested_documents=int(raw.get("ingested_documents") or 0),
        ingested_chunks=int(raw.get("ingested_chunks") or 0),
        skipped_ingest=int(raw.get("skipped_ingest") or 0),
        updated_at=raw.get("updated_at"),
    )


def save_progress(
    state: BulkBackfillState,
    path: Path,
    *,
    next_offset: int,
    catalog_pages: int | None = None,
    manifest_rows: int | None = None,
    downloaded: int | None = None,
    skipped_downloads: int | None = None,
    failed_downloads: int | None = None,
    ingested_sources: int | None = None,
    ingested_documents: int | None = None,
    ingested_chunks: int | None = None,
    skipped_ingest: int | None = None,
) -> BulkBackfillState:
    updated = BulkBackfillState(
        next_offset=next_offset,
        catalog_pages=state.catalog_pages if catalog_pages is None else catalog_pages,
        manifest_rows=state.manifest_rows if manifest_rows is None else manifest_rows,
        downloaded=state.downloaded if downloaded is None else downloaded,
        skipped_downloads=(
            state.skipped_downloads if skipped_downloads is None else skipped_downloads
        ),
        failed_downloads=state.failed_downloads if failed_downloads is None else failed_downloads,
        ingested_sources=state.ingested_sources if ingested_sources is None else ingested_sources,
        ingested_documents=(
            state.ingested_documents if ingested_documents is None else ingested_documents
        ),
        ingested_chunks=state.ingested_chunks if ingested_chunks is None else ingested_chunks,
        skipped_ingest=state.skipped_ingest if skipped_ingest is None else skipped_ingest,
        updated_at=datetime.now(UTC).isoformat(),
    )
    path.write_text(json.dumps(updated.__dict__, ensure_ascii=False, indent=2), encoding="utf-8")
    return updated


def _record_failed_page(
    failure_log_path: Path, offset: int, url: str, status_code: int, error_msg: str
) -> None:
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "offset": offset,
        "url": url,
        "status_code": status_code,
        "error": error_msg,
    }
    with failure_log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
