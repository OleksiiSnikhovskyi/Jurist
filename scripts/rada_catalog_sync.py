from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.prepare_priority_legal_source_manifest import (  # noqa: E402
    OUTPUT_FIELDS,
    prepare_manifest_rows,
)

RADA_LAWS_URL = "https://zakon.rada.gov.ua/laws"
RADA_NEW_ARRIVALS_URL = "https://zakon.rada.gov.ua/laws/main/nn"

DEFAULT_USER_AGENT = "JuristBot/1.0 (Browser-like; +https://github.com/OleksiiSnikhovskyi/Jurist)"
DEFAULT_REQUEST_TIMEOUT = 30.0

logger = logging.getLogger(__name__)

DOCUMENT_TYPE_MAP = {
    "Конституція України": "constitution",
    "Конституція": "constitution",
    "Кодекс України": "code",
    "Кодекс": "code",
    "Закон": "law",
    "Постанова": "cabinet_resolution",
    "Наказ": "executive_regulation",
    "Роз'яснення": "state_explanation",
    "Узагальнення судової практики": "supreme_court_position",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Convert official zakon.rada.gov.ua arrivals/catalog HTML into a legal-source manifest."
        )
    )
    parser.add_argument(
        "--input",
        default=RADA_NEW_ARRIVALS_URL,
        help="Local HTML file or URL. Defaults to the official newest arrivals page.",
    )
    parser.add_argument("--output", required=True, help="Target CSV or JSON manifest path.")
    parser.add_argument(
        "--documents-dir",
        default="legal_sources",
        help="Root folder for downloaded official document HTML files.",
    )
    parser.add_argument(
        "--download-documents",
        action="store_true",
        help="Download each official document HTML referenced by the prepared manifest.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite downloaded document files that already exist.",
    )
    parser.add_argument(
        "--base-url",
        default="https://zakon.rada.gov.ua",
        help="Base URL for relative links in saved HTML exports.",
    )
    parser.add_argument(
        "--today",
        default=datetime.now(UTC).date().isoformat(),
        help="Last-check date for manifest rows.",
    )
    parser.add_argument("--allow-issues", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with an error when any source row has validation issues.",
    )
    args = parser.parse_args()

    html = read_input(args.input)
    rows = parse_rada_arrivals_html(html, base_url=args.base_url, checked_at=args.today)
    prepared, issues = prepare_manifest_rows(
        rows,
        today=args.today,
        allow_issues=args.allow_issues,
    )
    write_manifest(Path(args.output), prepared)
    download_result = {"downloaded": 0, "skipped": 0, "failed": 0}
    if args.download_documents:
        download_result = download_manifest_documents(
            prepared,
            documents_dir=Path(args.documents_dir),
            overwrite=args.overwrite,
        )

    print(
        "rada_rows={rows} output_rows={output} issues={issues} "
        "downloaded={downloaded} skipped={skipped} failed={failed}".format(
            rows=len(rows),
            output=len(prepared),
            issues=len(issues),
            **download_result,
        )
    )
    for issue in issues:
        print(f"{issue['row']}: {issue['field']}: {issue['message']}")
    if issues and args.strict and not args.allow_issues:
        raise SystemExit(1)


def parse_rada_arrivals_html(
    html: str,
    *,
    base_url: str = "https://zakon.rada.gov.ua",
    checked_at: str,
) -> list[dict[str, Any]]:
    parser = _RadaListParser(base_url=base_url)
    parser.feed(html)
    return [
        row
        for item in parser.items
        if (row := _item_to_manifest_row(item, checked_at=checked_at))
    ]


def read_input(
    value: str, *, user_agent: str = DEFAULT_USER_AGENT, timeout: float = DEFAULT_REQUEST_TIMEOUT
) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        fetch_url = _relay_url_for(value) or value
        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, identity",
            "Referer": "https://zakon.rada.gov.ua/laws/main",
            "Connection": "keep-alive",
        }
        if fetch_url != value:
            headers["X-JUR-RADA-FETCH-TOKEN"] = os.getenv("JUR_RADA_FETCH_RELAY_TOKEN", "")
        request = Request(fetch_url, headers=headers)
        request.headers.update(headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                return _decode_response_body(response.read(), response.headers.get("Content-Encoding"))
        except HTTPError as exc:
            body_excerpt = ""
            try:
                body = exc.read()[:300].decode("utf-8", errors="ignore")
                body_excerpt = f" | body_excerpt={body!r}"
            except Exception:
                pass
            logger.error(f"HTTP {exc.code} fetching {value} via {fetch_url}{body_excerpt}")
            raise
    return Path(value).read_text(encoding="utf-8", errors="ignore")


def _relay_url_for(value: str) -> str | None:
    relay_url = os.getenv("JUR_RADA_FETCH_RELAY_URL", "").strip()
    if not relay_url:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "zakon.rada.gov.ua":
        return None
    separator = "&" if "?" in relay_url else "?"
    return f"{relay_url}{separator}url={quote(value, safe='')}"


def _decode_response_body(raw: bytes, content_encoding: str | None) -> str:
    encoding = (content_encoding or "").lower()
    if "gzip" in encoding or raw.startswith(b"\x1f\x8b"):
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="ignore")


def download_manifest_documents(
    rows: list[dict[str, str]],
    *,
    documents_dir: Path,
    overwrite: bool = False,
    fetcher: Any = read_input,
) -> dict[str, int]:
    counts = {"downloaded": 0, "skipped": 0, "failed": 0}
    documents_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        source_url = row.get("source_url") or ""
        file_path = row.get("file_path") or ""
        if not source_url or not file_path:
            counts["failed"] += 1
            continue
        target = documents_dir / file_path
        if target.exists() and not overwrite:
            counts["skipped"] += 1
            continue
        try:
            html = fetcher(source_url)
        except Exception:
            counts["failed"] += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        counts["downloaded"] += 1
    return counts


def write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
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


class _RadaListParser(HTMLParser):
    def __init__(self, *, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.items: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._inside_anchor = False
        self._anchor_text: list[str] = []
        self._anchor_href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "li":
            self._finish_current()
            self._current = {"text": []}
        if tag == "a" and self._current is not None:
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href") or ""
            if "/laws/show/" in href or "/go/" in href:
                self._inside_anchor = True
                self._anchor_text = []
                self._anchor_href = href

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._inside_anchor and self._current is not None:
            title = _squash(" ".join(self._anchor_text))
            if title:
                self._current["title"] = title
                self._current["url"] = urljoin(self.base_url, self._anchor_href or "")
            self._inside_anchor = False
            self._anchor_text = []
            self._anchor_href = None
        if tag == "li":
            self._finish_current()

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text or self._current is None:
            return
        if self._inside_anchor:
            self._anchor_text.append(text)
        self._current["text"].append(text)

    def _finish_current(self) -> None:
        if self._current and self._current.get("title") and self._current.get("url"):
            self.items.append(self._current)
        self._current = None


def _item_to_manifest_row(item: dict[str, Any], *, checked_at: str) -> dict[str, Any] | None:
    source_url = str(item.get("url") or "")
    if not source_url:
        return None
    details = _squash(" ".join(str(part) for part in item.get("text", [])))
    source_name = _squash(str(item.get("title") or ""))
    adoption_date = _extract_adoption_date(details)
    document_number = _extract_document_number(details)
    source_type = _extract_source_type(details, source_name)
    validity_status = _extract_validity_status(details)
    effective_date = _extract_effective_date(details)
    revision_date = _extract_revision_date(details)
    validity_note = _extract_validity_note(details)
    document_code = _extract_document_code(source_url, details)

    return {
        "file_path": f"official_html/rada/{document_code}.html",
        "source_name": source_name,
        "source_type": source_type,
        "source_url": source_url,
        "jurisdiction": "Ukraine",
        "document_number": document_number,
        "adoption_date": adoption_date,
        "effective_date": effective_date,
        "revision_date": revision_date,
        "validity_status": validity_status,
        "validity_note": validity_note,
        "last_checked_at": checked_at,
        "topic_tags": _tags_for_source_type(source_type),
        "summary": details,
    }


def _extract_adoption_date(text: str) -> str:
    match = re.search(r"від\s+(\d{2})\.(\d{2})\.(\d{4})", text)
    if not match:
        return ""
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def _extract_document_number(text: str) -> str:
    match = re.search(r"№\s*([^\s,;]+)", text)
    if match:
        return match.group(1).strip()
    code_match = re.search(r"\b([a-zа-яіїєґ]?\d{3,5}[_-][\w/-]+)\b", text, re.IGNORECASE)
    return code_match.group(1).strip() if code_match else ""


def _extract_source_type(details: str, source_name: str) -> str:
    haystack = f"{details} {source_name}"
    for label, source_type in DOCUMENT_TYPE_MAP.items():
        if label in haystack:
            return source_type
    return "law"


def _extract_validity_status(text: str) -> str:
    if "Втратив чинність" in text or "Не чинний" in text:
        return "obsolete"
    if "Набирає чинності" in text:
        return "pending_effective"
    if "Чинний" in text:
        return "current"
    return "needs_verification"


def _date_match_to_iso(match: re.Match[str]) -> str:
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def _extract_effective_date(text: str) -> str:
    patterns = [
        r"(?:Набирає чинності|набирає чинності|Вводиться в дію|вводиться в дію|Чинний з|чинний з)\s+(?:з\s+)?(\d{2})\.(\d{2})\.(\d{4})",
        r"(?:набрання чинності|введення в дію)[^\d]{0,80}(\d{2})\.(\d{2})\.(\d{4})",
    ]
    for pattern in patterns:
        if match := re.search(pattern, text):
            return _date_match_to_iso(match)
    return ""


def _extract_revision_date(text: str) -> str:
    patterns = [
        r"(?:Редакція від|редакція від)\s+(\d{2})\.(\d{2})\.(\d{4})",
        r"(?:станом на|Станом на)\s+(\d{2})\.(\d{2})\.(\d{4})",
    ]
    for pattern in patterns:
        if match := re.search(pattern, text):
            return _date_match_to_iso(match)
    return ""


def _extract_validity_note(text: str) -> str:
    patterns = [
        r"(Набирає чинності[^.;,\n]*(?:\d{2}\.\d{2}\.\d{4})?)",
        r"(Вводиться в дію[^.;,\n]*(?:\d{2}\.\d{2}\.\d{4})?)",
        r"(Редакція від\s+\d{2}\.\d{2}\.\d{4})",
        r"(Чинний[^.;,\n]*)",
        r"(Втратив чинність[^.;,\n]*)",
        r"(Не чинний[^.;,\n]*)",
    ]
    for pattern in patterns:
        if match := re.search(pattern, text):
            return _squash(match.group(1))
    return ""


def _extract_document_code(source_url: str, details: str) -> str:
    path = urlparse(source_url).path.rstrip("/")
    code = path.split("/")[-1] if path else ""
    if code and code not in {"show", "go"}:
        return _safe_slug(code)
    return _safe_slug(_extract_document_number(details) or "rada-document")


def _tags_for_source_type(source_type: str) -> str:
    tags = {
        "constitution": "constitution; official-source; rada",
        "code": "code; official-source; rada",
        "law": "law; official-source; rada",
        "cabinet_resolution": "cabinet; regulation; official-source; rada",
        "executive_regulation": "executive-regulation; official-source; rada",
        "state_explanation": "state-explanation; official-source; rada",
        "supreme_court_position": "court-practice; official-source; rada",
    }
    return tags.get(source_type, "official-source; rada")


def _safe_slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "rada-document"


def _squash(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


if __name__ == "__main__":
    main()

