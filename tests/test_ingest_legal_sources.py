import shutil
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.ingest_legal_sources import (
    SourceManifestEntry,
    iter_source_files,
    load_manifest,
    parse_date,
    parse_manifest_entry,
    parse_tags,
)


@pytest.fixture()
def source_dir() -> Generator[Path, None, None]:
    path = Path("test_uploads") / f"legal-sources-{uuid4()}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_parse_manifest_entry_supports_common_notebook_export_fields() -> None:
    entry = parse_manifest_entry(
        {
            "filename": "laws/civil-code.md",
            "title": "Цивільний кодекс України",
            "url": "https://zakon.rada.gov.ua/laws/show/435-15",
            "number": "435-IV",
            "adoption_date": "16.01.2003",
            "tags": "civil, code",
        }
    )

    assert entry == SourceManifestEntry(
        file_path="laws/civil-code.md",
        source_name="Цивільний кодекс України",
        source_type=None,
        source_url="https://zakon.rada.gov.ua/laws/show/435-15",
        jurisdiction=None,
        document_number="435-IV",
        adoption_date=parse_date("2003-01-16"),
        effective_date=None,
        validity_status=None,
        topic_tags=["civil", "code"],
        summary=None,
    )


def test_load_manifest_from_csv(source_dir: Path) -> None:
    manifest_path = source_dir / "sources.csv"
    manifest_path.write_text(
        "file_path,source_name,topic_tags\nlaw.md,Закон,\"tag1; tag2\"\n",
        encoding="utf-8",
    )

    manifest = load_manifest(manifest_path)

    assert manifest["law.md"].source_name == "Закон"
    assert manifest["law.md"].topic_tags == ["tag1", "tag2"]


def test_iter_source_files_filters_supported_extensions(source_dir: Path) -> None:
    supported = source_dir / "law.txt"
    ignored = source_dir / "image.png"
    nested = source_dir / "nested"
    nested.mkdir()
    nested_supported = nested / "code.md"
    supported.write_text("law", encoding="utf-8")
    ignored.write_text("nope", encoding="utf-8")
    nested_supported.write_text("code", encoding="utf-8")

    files = iter_source_files([source_dir])

    assert files == [supported, nested_supported]


def test_parse_tags_accepts_lists_and_delimited_strings() -> None:
    assert parse_tags(["civil", " code "]) == ["civil", "code"]
    assert parse_tags("civil; code, court") == ["civil", "code", "court"]
