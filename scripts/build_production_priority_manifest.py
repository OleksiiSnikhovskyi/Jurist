from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.prepare_priority_legal_source_manifest import (  # noqa: E402
    OUTPUT_FIELDS,
    prepare_manifest_rows,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build the production priority_manifest.csv from official source exports."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        default=["legal_sources/rada_bulk_manifest.csv"],
        help="CSV/JSON official-source manifests to merge. Defaults to Rada bulk manifest.",
    )
    parser.add_argument(
        "--output",
        default="legal_sources/priority_manifest.csv",
        help="Target production manifest path.",
    )
    parser.add_argument(
        "--documents-dir",
        default="legal_sources",
        help="Root folder used to verify manifest file_path entries.",
    )
    parser.add_argument(
        "--allow-missing-files",
        action="store_true",
        help="Keep rows even when their local official export file is missing.",
    )
    parser.add_argument(
        "--allow-issues",
        action="store_true",
        help="Keep rows with policy issues. Intended only for diagnostics.",
    )
    parser.add_argument(
        "--summary",
        default="legal_sources/priority_manifest.summary.json",
        help="Write a JSON build summary for audit/review.",
    )
    args = parser.parse_args()

    result = build_priority_manifest(
        input_paths=[Path(item) for item in args.inputs],
        output_path=Path(args.output),
        documents_dir=Path(args.documents_dir),
        summary_path=Path(args.summary),
        allow_missing_files=args.allow_missing_files,
        allow_issues=args.allow_issues,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["missing_files"] and not args.allow_missing_files:
        raise SystemExit(1)
    if result["issues"] and args.allow_issues:
        raise SystemExit(1)


def build_priority_manifest(
    *,
    input_paths: list[Path],
    output_path: Path,
    documents_dir: Path,
    summary_path: Path | None = None,
    allow_missing_files: bool = False,
    allow_issues: bool = False,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    per_input: list[dict[str, Any]] = []
    for input_path in input_paths:
        loaded = load_rows(input_path)
        rows.extend(loaded)
        per_input.append({"path": str(input_path), "rows": len(loaded)})

    prepared, issues = prepare_manifest_rows(rows, today="", allow_issues=allow_issues)
    existing, missing = split_by_existing_files(prepared, documents_dir=documents_dir)
    output_rows = existing if not allow_missing_files else prepared
    write_manifest(output_path, output_rows)

    has_missing_files = bool(missing) and not allow_missing_files
    has_unfiltered_issues = bool(issues) and allow_issues
    result = {
        "ok": not has_missing_files and not has_unfiltered_issues,
        "inputs": per_input,
        "input_rows": len(rows),
        "output_rows": len(output_rows),
        "issues": len(issues),
        "missing_files": len(missing),
        "output": str(output_path),
        "summary": str(summary_path) if summary_path else None,
        "issue_examples": issues[:10],
        "missing_file_examples": missing[:10],
    }
    if summary_path:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else raw.get("sources", [])
        return [dict(row) for row in rows]
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    raise ValueError(f"Unsupported manifest format: {path}")


def split_by_existing_files(
    rows: list[dict[str, str]], *, documents_dir: Path
) -> tuple[list[dict[str, str]], list[str]]:
    existing: list[dict[str, str]] = []
    missing: list[str] = []
    for row in rows:
        file_path = row.get("file_path") or ""
        if not file_path:
            missing.append("")
            continue
        if (documents_dir / file_path).exists():
            existing.append(row)
        else:
            missing.append(file_path)
    return existing, missing


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
