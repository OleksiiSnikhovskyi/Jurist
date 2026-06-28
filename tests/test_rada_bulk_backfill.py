import inspect
import json
import shutil
import time
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from scripts.rada_bulk_backfill import (
    BulkBackfillState,
    build_catalog_page_url,
    fetch_catalog_page_with_retries,
    filter_manifest_rows,
    load_state,
    run_backfill,
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


def test_build_catalog_page_url_uses_rada_page_numbers() -> None:
    base_url = "https://zakon.rada.gov.ua/laws/main/a/page"

    assert build_catalog_page_url(base_url, 1) == base_url
    assert build_catalog_page_url(base_url, 51) == f"{base_url}51"
    assert build_catalog_page_url(f"{base_url}/", 101) == f"{base_url}101"
    assert build_catalog_page_url(base_url, 1000) == f"{base_url}1000/"


def test_build_catalog_page_url_with_url_style_slash() -> None:
    base_url = "https://zakon.rada.gov.ua/laws/main/a/page"

    assert build_catalog_page_url(base_url, 1, url_style="slash") == base_url
    assert build_catalog_page_url(base_url, 50, url_style="slash") == f"{base_url}/50/"
    assert build_catalog_page_url(base_url, 1844, url_style="slash") == f"{base_url}/1844/"


def test_build_catalog_page_url_with_url_style_no_slash() -> None:
    base_url = "https://zakon.rada.gov.ua/laws/main/a/page"

    assert build_catalog_page_url(base_url, 1, url_style="no-slash") == base_url
    assert build_catalog_page_url(base_url, 50, url_style="no-slash") == f"{base_url}50"
    assert build_catalog_page_url(base_url, 1844, url_style="no-slash") == f"{base_url}1844"


def test_backfill_uses_sequential_rada_page_numbers_by_default() -> None:
    assert inspect.signature(run_backfill).parameters["page_size"].default == 1


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


def test_fetch_catalog_page_retries_before_raising() -> None:
    attempts = {"count": 0}

    def flaky_fetcher(_url: str) -> str:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("temporary")
        return "<html></html>"

    assert fetch_catalog_page_with_retries(
        "https://zakon.rada.gov.ua/laws/main/a/page",
        fetcher=flaky_fetcher,
        retries=2,
        retry_seconds=0,
    ) == "<html></html>"
    assert attempts["count"] == 2


def test_backfill_stops_gracefully_when_catalog_fetch_fails(backfill_dir: Path) -> None:
    def failing_fetcher(_url: str) -> str:
        raise RuntimeError("forbidden")

    result = run_backfill(
        catalog_url="https://zakon.rada.gov.ua/laws/main/a/page",
        documents_dir=backfill_dir / "documents",
        manifest_path=backfill_dir / "manifest.csv",
        state_path=backfill_dir / "state.json",
        workspace_id="workspace-1",
        workspace_name="Workspace",
        user_id="user-1",
        user_email="user@example.com",
        user_name="User",
        limit_pages=1,
        sleep_seconds=0,
        catalog_retries=1,
        catalog_retry_seconds=0,
        current_only=True,
        dry_run=True,
        fetcher=failing_fetcher,
    )

    assert result["ok"] is False
    assert result["pages_this_run"] == 0
    assert result["next_offset"] == 1
    assert str(result["stopped_reason"]).startswith("catalog_fetch_failed:RuntimeError")


def test_fetch_catalog_page_with_exponential_backoff() -> None:
    sleep_times = []

    def mock_sleep(seconds: float) -> None:
        sleep_times.append(seconds)

    attempts = {"count": 0}

    def flaky_fetcher(_url: str) -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary")
        return "<html></html>"

    with patch("time.sleep", side_effect=mock_sleep):
        result = fetch_catalog_page_with_retries(
            "https://zakon.rada.gov.ua/laws/main/a/page",
            fetcher=flaky_fetcher,
            retries=3,
            retry_seconds=1.0,
            jitter_seconds=0.0,
        )

    assert result == "<html></html>"
    assert attempts["count"] == 3
    assert len(sleep_times) == 2
    assert sleep_times[0] == 1.0
    assert sleep_times[1] == 2.0


def test_fetch_catalog_page_with_jitter() -> None:
    sleep_times = []

    def mock_sleep(seconds: float) -> None:
        sleep_times.append(seconds)

    attempts = {"count": 0}

    def flaky_fetcher(_url: str) -> str:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("temporary")
        return "<html></html>"

    with patch("time.sleep", side_effect=mock_sleep):
        result = fetch_catalog_page_with_retries(
            "https://zakon.rada.gov.ua/laws/main/a/page",
            fetcher=flaky_fetcher,
            retries=1,
            retry_seconds=1.0,
            jitter_seconds=0.5,
        )

    assert result == "<html></html>"
    assert len(sleep_times) == 1
    assert 1.0 <= sleep_times[0] <= 1.5


def test_backfill_skips_forbidden_pages_and_logs_them(backfill_dir: Path) -> None:
    forbidden_response = HTTPError(
        "https://zakon.rada.gov.ua/laws/main/a/page1844/",
        403,
        "Forbidden",
        {},
        None,
    )
    attempts = {"count": 0}

    def forbidden_fetcher(_url: str) -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise forbidden_response
        return "<html></html>"

    failure_log = backfill_dir / "failures.log"

    result = run_backfill(
        catalog_url="https://zakon.rada.gov.ua/laws/main/a/page",
        documents_dir=backfill_dir / "documents",
        manifest_path=backfill_dir / "manifest.csv",
        state_path=backfill_dir / "state.json",
        workspace_id="workspace-1",
        workspace_name="Workspace",
        user_id="user-1",
        user_email="user@example.com",
        user_name="User",
        limit_pages=2,
        sleep_seconds=0,
        catalog_retries=0,
        catalog_retry_seconds=0,
        current_only=True,
        dry_run=True,
        skip_forbidden_pages=True,
        failure_log_path=failure_log,
        fetcher=forbidden_fetcher,
    )

    assert result["ok"] is True or result["pages_this_run"] >= 1
    assert result["next_offset"] >= 2
    assert failure_log.exists()

    with failure_log.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) >= 1

    record = json.loads(lines[0])
    assert record["offset"] == 1
    assert record["status_code"] == 403
    assert "Forbidden" in record["error"]


def test_backfill_stops_on_403_without_skip_forbidden_pages(backfill_dir: Path) -> None:
    forbidden_response = HTTPError(
        "https://zakon.rada.gov.ua/laws/main/a/page1844/",
        403,
        "Forbidden",
        {},
        None,
    )

    def forbidden_fetcher(_url: str) -> str:
        raise forbidden_response

    result = run_backfill(
        catalog_url="https://zakon.rada.gov.ua/laws/main/a/page",
        documents_dir=backfill_dir / "documents",
        manifest_path=backfill_dir / "manifest.csv",
        state_path=backfill_dir / "state.json",
        workspace_id="workspace-1",
        workspace_name="Workspace",
        user_id="user-1",
        user_email="user@example.com",
        user_name="User",
        limit_pages=1,
        sleep_seconds=0,
        catalog_retries=0,
        catalog_retry_seconds=0,
        current_only=True,
        dry_run=True,
        skip_forbidden_pages=False,
        fetcher=forbidden_fetcher,
    )

    assert result["ok"] is False
    assert "403" in str(result["stopped_reason"])
