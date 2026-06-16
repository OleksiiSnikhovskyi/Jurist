from pathlib import Path
import shutil
from collections.abc import Generator
from uuid import uuid4

import pytest

from scripts.rada_bulk_backfill import (
    BulkBackfillState,
    build_catalog_page_url,
    filter_manifest_rows,
    load_state,
    save_progress,
)


@pytest.fixture()
def backfill_dir() -> Generator[Path, None, None]:
    path = Path("test_uploads") / f"rada-bulk-{uuid4()}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_build_catalog_page_url_uses_rada_offsets() -> None:
    base_url = "https://zakon.rada.gov.ua/laws/main/a/page"

    assert build_catalog_page_url(base_url, 1) == base_url
    assert build_catalog_page_url(base_url, 51) == f"{base_url}51"
    assert build_catalog_page_url(f"{base_url}/", 101) == f"{base_url}101"


def test_filter_manifest_rows_defaults_to_current_only() -> None:
    rows = [
        {"source_name": "Current law", "validity_status": "current"},
        {"source_name": "Pending law", "validity_status": "pending_effective"},
        {"source_name": "Old law", "validity_status": "obsolete"},
        {"source_name": "Unknown law", "validity_status": "needs_verification"},
    ]

    assert filter_manifest_rows(rows, current_only=True) == [rows[0]]
    assert filter_manifest_rows(rows, current_only=False) == rows


def test_backfill_state_round_trip(backfill_dir: Path) -> None:
    state_path = backfill_dir / "state.json"

    updated = save_progress(
        BulkBackfillState(),
        state_path,
        next_offset=51,
        catalog_pages=1,
        manifest_rows=40,
        downloaded=40,
        skipped_downloads=2,
        failed_downloads=1,
        ingested_sources=37,
        ingested_documents=37,
        ingested_chunks=120,
        skipped_ingest=3,
    )

    loaded = load_state(state_path)

    assert loaded == updated
    assert loaded.next_offset == 51
    assert loaded.manifest_rows == 40
    assert loaded.ingested_chunks == 120
