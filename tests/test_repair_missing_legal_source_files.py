import csv
import shutil
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.repair_missing_legal_source_files import repair_missing_files


@pytest.fixture()
def repair_dir() -> Generator[Path, None, None]:
    path = Path("test_uploads") / f"repair-missing-{uuid4()}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_repair_missing_files_downloads_only_missing_manifest_files(repair_dir: Path) -> None:
    documents_dir = repair_dir / "legal_sources"
    existing = documents_dir / "official_html/rada/existing.html"
    existing.parent.mkdir(parents=True)
    existing.write_text("<html>existing</html>", encoding="utf-8")

    manifest_path = repair_dir / "manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["file_path", "source_url", "source_name"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "file_path": "official_html/rada/existing.html",
                "source_url": "https://zakon.rada.gov.ua/laws/show/1",
                "source_name": "Existing",
            }
        )
        writer.writerow(
            {
                "file_path": "official_html/rada/missing.html",
                "source_url": "https://zakon.rada.gov.ua/laws/show/2",
                "source_name": "Missing",
            }
        )

    fetched_urls: list[str] = []

    def fake_fetcher(url: str) -> str:
        fetched_urls.append(url)
        return "<html>downloaded</html>"

    result = repair_missing_files(
        manifest_path=manifest_path,
        documents_dir=documents_dir,
        sleep_seconds=0,
        fetcher=fake_fetcher,
    )

    assert result["ok"] is True
    assert result["missing_before"] == 1
    assert result["downloaded"] == 1
    assert fetched_urls == ["https://zakon.rada.gov.ua/laws/show/2"]
    assert (documents_dir / "official_html/rada/missing.html").read_text(encoding="utf-8") == (
        "<html>downloaded</html>"
    )
