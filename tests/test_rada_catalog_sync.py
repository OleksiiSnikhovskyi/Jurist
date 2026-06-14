import gzip
import shutil
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.prepare_priority_legal_source_manifest import prepare_manifest_rows
from scripts.rada_catalog_sync import (
    _decode_response_body,
    download_manifest_documents,
    parse_rada_arrivals_html,
)


@pytest.fixture()
def sync_dir() -> Generator[Path, None, None]:
    path = Path("test_uploads") / f"rada-sync-{uuid4()}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_parse_rada_arrivals_html_builds_manifest_rows() -> None:
    html = """
    <html><body>
      <ol>
        <li>
          <a href="/laws/show/4782-20">
            Про внесення зміни до статті 23 Закону України
          </a>
          Верховна Рада України; Закон від 11.02.2026 № 4782-IX
          4782-IX, Набирає чинності, 5 кб
        </li>
        <li>
          <a href="/laws/show/282-2026-%D0%BF">
            Про внесення змін до постанов Кабінету Міністрів України
          </a>
          Кабінет Міністрів України; Постанова від 25.02.2026 № 282
          282-2026-п, Чинний, 36 кб
        </li>
      </ol>
    </body></html>
    """

    rows = parse_rada_arrivals_html(html, checked_at="2026-06-14")

    assert len(rows) == 2
    assert rows[0]["source_name"] == "Про внесення зміни до статті 23 Закону України"
    assert rows[0]["source_type"] == "law"
    assert rows[0]["document_number"] == "4782-IX"
    assert rows[0]["adoption_date"] == "2026-02-11"
    assert rows[0]["validity_status"] == "pending_effective"
    assert rows[0]["source_url"] == "https://zakon.rada.gov.ua/laws/show/4782-20"
    assert rows[1]["source_type"] == "cabinet_resolution"
    assert rows[1]["validity_status"] == "current"


def test_rada_rows_pass_priority_manifest_validation() -> None:
    html = Path("tests/fixtures/rada_new_arrivals.html").read_text(encoding="utf-8")

    rows = parse_rada_arrivals_html(html, checked_at="2026-06-14")
    prepared, issues = prepare_manifest_rows(rows, today="2026-06-14")

    assert issues == []
    assert prepared[0]["source_url"].startswith("https://zakon.rada.gov.ua/laws/show/")
    assert prepared[0]["last_checked_at"] == "2026-06-14"


def test_download_manifest_documents_writes_official_html(sync_dir: Path) -> None:
    rows = [
        {
            "source_url": "https://zakon.rada.gov.ua/laws/show/4777-20",
            "file_path": "official_html/rada/4777-20.html",
        }
    ]

    counts = download_manifest_documents(
        rows,
        documents_dir=sync_dir,
        fetcher=lambda url: f"<html><body>{url}</body></html>",
    )

    target = sync_dir / "official_html" / "rada" / "4777-20.html"
    assert counts == {"downloaded": 1, "skipped": 0, "failed": 0}
    assert target.read_text(encoding="utf-8") == (
        "<html><body>https://zakon.rada.gov.ua/laws/show/4777-20</body></html>"
    )

    second_counts = download_manifest_documents(
        rows,
        documents_dir=sync_dir,
        fetcher=lambda url: "changed",
    )

    assert second_counts == {"downloaded": 0, "skipped": 1, "failed": 0}
    assert "changed" not in target.read_text(encoding="utf-8")


def test_decode_response_body_supports_gzip() -> None:
    raw = gzip.compress("Найновіші надходження".encode())

    assert _decode_response_body(raw, "gzip") == "Найновіші надходження"
