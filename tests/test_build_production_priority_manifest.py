import csv
import shutil
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.build_production_priority_manifest import build_priority_manifest


@pytest.fixture()
def manifest_dir() -> Generator[Path, None, None]:
    path = Path("test_uploads") / f"priority-manifest-{uuid4()}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_build_priority_manifest_filters_missing_files(manifest_dir: Path) -> None:
    documents_dir = manifest_dir / "legal_sources"
    existing_file = documents_dir / "official_html/rada/law-1.html"
    existing_file.parent.mkdir(parents=True)
    existing_file.write_text("<html>law</html>", encoding="utf-8")

    input_path = manifest_dir / "rada_bulk_manifest.csv"
    with input_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "file_path",
                "source_name",
                "source_type",
                "source_url",
                "jurisdiction",
                "document_number",
                "adoption_date",
                "effective_date",
                "validity_status",
                "last_checked_at",
                "topic_tags",
                "summary",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "file_path": "official_html/rada/law-1.html",
                "source_name": "Закон України",
                "source_type": "law",
                "source_url": "https://zakon.rada.gov.ua/laws/show/1",
                "jurisdiction": "Ukraine",
                "document_number": "1",
                "adoption_date": "2024-01-01",
                "effective_date": "",
                "validity_status": "current",
                "last_checked_at": "2026-06-17",
                "topic_tags": "law",
                "summary": "",
            }
        )
        writer.writerow(
            {
                "file_path": "official_html/rada/missing.html",
                "source_name": "Закон України 2",
                "source_type": "law",
                "source_url": "https://zakon.rada.gov.ua/laws/show/2",
                "jurisdiction": "Ukraine",
                "document_number": "2",
                "adoption_date": "2024-01-02",
                "effective_date": "",
                "validity_status": "current",
                "last_checked_at": "2026-06-17",
                "topic_tags": "law",
                "summary": "",
            }
        )

    output_path = documents_dir / "priority_manifest.csv"
    summary_path = documents_dir / "priority_manifest.summary.json"
    result = build_priority_manifest(
        input_paths=[input_path],
        output_path=output_path,
        documents_dir=documents_dir,
        summary_path=summary_path,
    )

    assert result["ok"] is False
    assert result["input_rows"] == 2
    assert result["output_rows"] == 1
    assert result["missing_files"] == 1
    assert summary_path.exists()

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert [row["file_path"] for row in rows] == ["official_html/rada/law-1.html"]
