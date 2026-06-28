from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.legal_source_policy import (  # noqa: E402
    deduplicate_manifest_rows,
    validate_priority_source_entry,
)

OUTPUT_FIELDS = [
    "file_path",
    "source_name",
    "source_type",
    "source_url",
    "jurisdiction",
    "document_number",
    "adoption_date",
    "effective_date",
    "revision_date",
    "validity_status",
    "validity_note",
    "last_checked_at",
    "topic_tags",
    "summary",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a validated priority legal-source manifest for PostgreSQL/pgvector ingestion."
        )
    )
    parser.add_argument(
        "input",
        help="CSV or JSON file exported from NotebookLM, Google Drive, GitHub, or Nextcloud.",
    )
    parser.add_argument("--output", required=True, help="Target CSV or JSON manifest path.")
    parser.add_argument(
        "--allow-issues",
        action="store_true",
        help="Write rows even when they have validation issues; issues are still reported.",
    )
    parser.add_argument(
        "--today",
        default=datetime.now(UTC).date().isoformat(),
        help="Last-check date to use when a row has no last_checked_at.",
    )
    args = parser.parse_args()

    rows = load_rows(Path(args.input))
    prepared, issues = prepare_manifest_rows(rows, today=args.today, allow_issues=args.allow_issues)
    write_rows(Path(args.output), prepared)

    print(f"input_rows={len(rows)} output_rows={len(prepared)} issues={len(issues)}")
    for issue in issues:
        print(f"{issue['row']}: {issue['field']}: {issue['message']}")
    if issues and not args.allow_issues:
        raise SystemExit(1)


def prepare_manifest_rows(
    rows: list[dict[str, Any]], *, today: str, allow_issues: bool = False
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    normalized = [normalize_row(row, today=today) for row in rows]
    deduped = deduplicate_manifest_rows(normalized)
    prepared: list[dict[str, str]] = []
    issues: list[dict[str, str]] = []

    for index, row in enumerate(deduped, start=1):
        row_issues = validate_priority_source_entry(row)
        for issue in row_issues:
            issues.append({"row": str(index), "field": issue.field, "message": issue.message})
        if row_issues and not allow_issues:
            continue
        prepared.append({field: str(row.get(field) or "") for field in OUTPUT_FIELDS})
    return prepared, issues


def normalize_row(row: dict[str, Any], *, today: str) -> dict[str, Any]:
    source_type = clean(row.get("source_type") or infer_source_type(row))
    adoption_date = parse_date(row.get("adoption_date")) if row.get("adoption_date") else None
    effective_date = parse_date(row.get("effective_date")) if row.get("effective_date") else None
    revision_date = parse_date(row.get("revision_date")) if row.get("revision_date") else None
    tags = parse_tags(row.get("topic_tags") or row.get("tags"))

    return {
        "file_path": clean(row.get("file_path") or row.get("path") or row.get("filename")),
        "source_name": clean(row.get("source_name") or row.get("title") or row.get("name")),
        "source_type": source_type,
        "source_url": clean(row.get("source_url") or row.get("url")),
        "jurisdiction": clean(row.get("jurisdiction")) or "Ukraine",
        "document_number": clean(row.get("document_number") or row.get("number")),
        "adoption_date": adoption_date.isoformat() if adoption_date else "",
        "effective_date": effective_date.isoformat() if effective_date else "",
        "revision_date": revision_date.isoformat() if revision_date else "",
        "validity_status": clean(row.get("validity_status") or row.get("status")) or "current",
        "validity_note": clean(row.get("validity_note") or row.get("effective_note") or row.get("status_note")),
        "last_checked_at": clean(row.get("last_checked_at") or row.get("checked_at")) or today,
        "topic_tags": "; ".join(tags),
        "summary": clean(row.get("summary")),
    }


def infer_source_type(row: dict[str, Any]) -> str:
    title = row.get("source_name") or row.get("title") or row.get("name") or ""
    url = row.get("source_url") or row.get("url") or ""
    text = f"{title} {url}".lower()
    if "конституц" in text:
        return "constitution"
    if "кодекс" in text:
        return "code"
    if "нкре" in text or "nerc.gov.ua" in text:
        return "nerc_decision"
    if "дбн" in text:
        return "dbn"
    if "дсту" in text:
        return "dstu"
    if "верховн" in text or "supreme.court.gov.ua" in text:
        return "supreme_court_position"
    if "кабінет" in text or "кму" in text or "kmu.gov.ua" in text:
        return "cabinet_resolution"
    if "роз'яснен" in text or "роз’яснен" in text:
        return "state_explanation"
    if "наказ" in text or "порядок" in text or "інструкц" in text:
        return "executive_regulation"
    return "law"


def load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else raw.get("sources", [])
        return [dict(row) for row in rows]
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    raise ValueError("Input must be .json or .csv")


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        content = json.dumps({"sources": rows}, ensure_ascii=False, indent=2)
        path.write_text(content, encoding="utf-8")
        return
    if path.suffix.lower() == ".csv":
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return
    raise ValueError("Output must be .json or .csv")


def clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    for date_format in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value}")


def parse_tags(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).replace(";", ",").split(",") if item.strip()]


if __name__ == "__main__":
    main()
