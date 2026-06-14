from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlparse

PRIORITY_SOURCE_TYPES: dict[str, str] = {
    "constitution": "Конституція України",
    "code": "Кодекси України",
    "law": "Закони України",
    "cabinet_resolution": "Постанови Кабінету Міністрів України",
    "executive_regulation": "Нормативні акти центральних органів виконавчої влади",
    "nerc_decision": "Рішення та постанови НКРЕКП",
    "dbn": "ДБН",
    "dstu": "ДСТУ",
    "state_explanation": "Роз'яснення державних органів",
    "supreme_court_position": "Огляди та правові позиції Верховного Суду",
}

OFFICIAL_DOMAINS: frozenset[str] = frozenset(
    {
        "zakon.rada.gov.ua",
        "court.gov.ua",
        "supreme.court.gov.ua",
        "kmu.gov.ua",
        "me.gov.ua",
        "minjust.gov.ua",
        "nerc.gov.ua",
    }
)

CURRENT_VALIDITY_STATUSES: frozenset[str] = frozenset(
    {
        "current",
        "active",
        "чинний",
        "чинна",
        "актуальна",
    }
)

OBSOLETE_VALIDITY_STATUSES: frozenset[str] = frozenset(
    {
        "obsolete",
        "expired",
        "inactive",
        "archived",
        "нечинний",
        "нечинна",
        "втратив чинність",
    }
)

BLOCKED_SOURCE_HINTS: frozenset[str] = frozenset(
    {
        "blog",
        "forum",
        "news",
        "новини",
        "comment",
        "коментар",
        "jurliga",
        "ligazakon",
        "pravo",
    }
)


@dataclass(frozen=True)
class SourceValidationIssue:
    field: str
    message: str


def normalize_domain(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    domain = parsed.netloc or parsed.path.split("/")[0]
    domain = domain.lower().split("@")[-1].split(":")[0].strip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    return domain or None


def is_official_source_url(url: str | None) -> bool:
    domain = normalize_domain(url)
    return bool(
        domain
        and any(domain == item or domain.endswith(f".{item}") for item in OFFICIAL_DOMAINS)
    )


def has_blocked_source_hint(url: str | None, source_name: str | None = None) -> bool:
    text = f"{url or ''} {source_name or ''}".lower()
    return any(hint in text for hint in BLOCKED_SOURCE_HINTS)


def normalize_validity_status(value: str | None) -> str:
    return (value or "needs_verification").strip().lower()


def is_current_validity_status(value: str | None) -> bool:
    return normalize_validity_status(value) in CURRENT_VALIDITY_STATUSES


def is_obsolete_validity_status(value: str | None) -> bool:
    return normalize_validity_status(value) in OBSOLETE_VALIDITY_STATUSES


def validate_priority_source_entry(row: dict[str, object]) -> list[SourceValidationIssue]:
    issues: list[SourceValidationIssue] = []
    source_name = _text(row.get("source_name") or row.get("title") or row.get("name"))
    source_type = _text(row.get("source_type"))
    source_url = _text(row.get("source_url") or row.get("url"))
    document_number = _text(row.get("document_number") or row.get("number"))
    adoption_date = row.get("adoption_date")
    topic_tags = row.get("topic_tags") or row.get("tags")
    validity_status = _text(row.get("validity_status") or row.get("status"))

    if not source_name:
        issues.append(SourceValidationIssue("source_name", "Document title is required."))
    if source_type and source_type not in PRIORITY_SOURCE_TYPES:
        issues.append(
            SourceValidationIssue("source_type", "Source type is not in the priority taxonomy.")
        )
    if not source_url:
        issues.append(SourceValidationIssue("source_url", "Official source URL is required."))
    elif not is_official_source_url(source_url):
        issues.append(
            SourceValidationIssue("source_url", "URL must belong to an approved official domain.")
        )
    if has_blocked_source_hint(source_url, source_name):
        issues.append(
            SourceValidationIssue(
                "source_url",
                "News, blogs, forums, and private commentary are excluded.",
            )
        )
    sources_without_number = {"constitution", "state_explanation", "supreme_court_position"}
    if not document_number and source_type not in sources_without_number:
        issues.append(
            SourceValidationIssue(
                "document_number",
                "Document number is required for this source type.",
            )
        )
    if not adoption_date:
        issues.append(
            SourceValidationIssue("adoption_date", "Adoption/publication date is required.")
        )
    if is_obsolete_validity_status(validity_status):
        issues.append(
            SourceValidationIssue("validity_status", "Obsolete or inactive revisions are excluded.")
        )
    if not topic_tags:
        issues.append(SourceValidationIssue("topic_tags", "At least one thematic tag is required."))
    return issues


def deduplicate_manifest_rows(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    best: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in rows:
        key = _dedupe_key(row)
        existing = best.get(key)
        if existing is None or _row_score(row) > _row_score(existing):
            best[key] = dict(row)
    return list(best.values())


def _dedupe_key(row: dict[str, object]) -> tuple[str, str, str]:
    source_url = _text(row.get("source_url") or row.get("url"))
    if source_url:
        return ("url", source_url.rstrip("/").lower(), "")
    name = _text(row.get("source_name") or row.get("title") or row.get("name")).lower()
    number = _text(row.get("document_number") or row.get("number")).lower()
    adopted = row.get("adoption_date")
    adopted_text = adopted.isoformat() if isinstance(adopted, date) else str(adopted or "").strip()
    return ("metadata", name, f"{number}:{adopted_text}")


def _row_score(row: dict[str, object]) -> int:
    score = 0
    if is_official_source_url(_text(row.get("source_url") or row.get("url"))):
        score += 100
    if is_current_validity_status(_text(row.get("validity_status") or row.get("status"))):
        score += 20
    if row.get("last_checked_at"):
        score += 10
    if row.get("file_path") or row.get("path") or row.get("filename"):
        score += 5
    return score


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
