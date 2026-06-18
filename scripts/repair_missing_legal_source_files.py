from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.rada_catalog_sync import read_input  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download missing official source files referenced by a legal-source manifest."
    )
    parser.add_argument("--manifest", default="legal_sources/rada_bulk_manifest.csv")
    parser.add_argument("--documents-dir", default="legal_sources")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    args = parser.parse_args()

    result = repair_missing_files(
        manifest_path=Path(args.manifest),
        documents_dir=Path(args.documents_dir),
        limit=args.limit,
        sleep_seconds=args.sleep_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["failed"] > 0:
        raise SystemExit(1)


def repair_missing_files(
    *,
    manifest_path: Path,
    documents_dir: Path,
    limit: int | None = None,
    sleep_seconds: float = 0.5,
    fetcher: Any = read_input,
) -> dict[str, Any]:
    missing_rows = find_missing_manifest_rows(manifest_path, documents_dir=documents_dir)
    if limit is not None:
        missing_rows = missing_rows[: max(0, limit)]

    downloaded = 0
    failed: list[dict[str, str]] = []
    for row in missing_rows:
        file_path = row.get("file_path") or ""
        source_url = row.get("source_url") or ""
        target = documents_dir / file_path
        if not file_path or not source_url:
            failed.append({"file_path": file_path, "source_url": source_url, "error": "missing path/url"})
            continue
        try:
            html = fetcher(source_url)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(html, encoding="utf-8")
            downloaded += 1
        except Exception as exc:
            failed.append({"file_path": file_path, "source_url": source_url, "error": str(exc)})
        time.sleep(max(0.0, sleep_seconds))

    return {
        "ok": not failed,
        "missing_before": len(missing_rows),
        "downloaded": downloaded,
        "failed": len(failed),
        "failed_examples": failed[:10],
    }


def find_missing_manifest_rows(
    manifest_path: Path, *, documents_dir: Path
) -> list[dict[str, str]]:
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]

    missing: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        file_path = row.get("file_path") or ""
        if not file_path or file_path in seen:
            continue
        seen.add(file_path)
        if not (documents_dir / file_path).exists():
            missing.append(row)
    return missing


if __name__ == "__main__":
    main()
