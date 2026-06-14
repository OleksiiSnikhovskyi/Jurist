from scripts.legal_source_policy import (
    deduplicate_manifest_rows,
    is_official_source_url,
    validate_priority_source_entry,
)
from scripts.prepare_priority_legal_source_manifest import prepare_manifest_rows


def test_official_source_url_accepts_priority_domains() -> None:
    assert is_official_source_url("https://zakon.rada.gov.ua/laws/show/435-15")
    assert is_official_source_url("https://supreme.court.gov.ua/supreme/pres-centr/news/")


def test_official_source_url_rejects_private_sources() -> None:
    assert not is_official_source_url("https://example-law-blog.test/material")
    assert not is_official_source_url("https://news.example.test/law")


def test_validate_priority_source_entry_rejects_unofficial_and_obsolete_rows() -> None:
    issues = validate_priority_source_entry(
        {
            "source_name": "Коментар до закону",
            "source_type": "law",
            "source_url": "https://private-blog.test/comment",
            "document_number": "1",
            "adoption_date": "2024-01-01",
            "validity_status": "obsolete",
            "topic_tags": "construction",
        }
    )

    assert {issue.field for issue in issues} == {"source_url", "validity_status"}


def test_deduplicate_manifest_rows_prefers_official_current_row() -> None:
    rows = [
        {
            "source_name": "Закон",
            "source_url": "https://zakon.rada.gov.ua/laws/show/1",
            "validity_status": "needs_verification",
        },
        {
            "source_name": "Закон",
            "source_url": "https://zakon.rada.gov.ua/laws/show/1",
            "validity_status": "current",
            "last_checked_at": "2026-06-14",
        },
    ]

    assert deduplicate_manifest_rows(rows) == [rows[1]]


def test_prepare_manifest_rows_normalizes_priority_catalog() -> None:
    prepared, issues = prepare_manifest_rows(
        [
            {
                "filename": "codes/civil-code.md",
                "title": "Цивільний кодекс України",
                "url": "https://zakon.rada.gov.ua/laws/show/435-15",
                "number": "435-IV",
                "adoption_date": "16.01.2003",
                "tags": "civil; code",
            }
        ],
        today="2026-06-14",
    )

    assert issues == []
    assert prepared[0]["file_path"] == "codes/civil-code.md"
    assert prepared[0]["source_type"] == "code"
    assert prepared[0]["last_checked_at"] == "2026-06-14"
    assert prepared[0]["topic_tags"] == "civil; code"
