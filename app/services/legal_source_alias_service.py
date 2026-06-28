import re
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy.orm import Session

from app.models.legal_source_alias import LegalSourceAlias


ALIAS_FRONTMATTER_KEYS = ("aliases", "alias", "legal_aliases", "legal_source_aliases")


def normalize_legal_alias(value: str) -> str:
    normalized = value.replace("’", "'").replace("`", "'")
    normalized = re.sub(r"\s+", " ", normalized, flags=re.MULTILINE)
    normalized = normalized.strip(" \t\r\n\"'“”«».,;:")
    return normalized.lower()


def normalize_alias_list(values: Iterable[Any]) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        alias = str(value).strip()
        normalized = normalize_legal_alias(alias)
        if not alias or not normalized or normalized in seen:
            continue
        aliases.append(alias)
        seen.add(normalized)
    return aliases


def extract_aliases_from_frontmatter(frontmatter: dict[str, Any]) -> list[str]:
    raw_aliases: list[Any] = []
    for key in ALIAS_FRONTMATTER_KEYS:
        value = frontmatter.get(key)
        if isinstance(value, list):
            raw_aliases.extend(value)
        elif value:
            raw_aliases.append(value)
    return normalize_alias_list(raw_aliases)


def build_obsidian_aliases(
    *,
    title: str | None,
    note_path: str,
    frontmatter: dict[str, Any],
) -> list[str]:
    path_title = PurePosixPath(note_path.replace("\\", "/")).stem
    raw_aliases: list[Any] = [title, path_title]
    raw_aliases.extend(extract_aliases_from_frontmatter(frontmatter))
    for key in ("source_name", "document_number"):
        value = frontmatter.get(key)
        if value:
            raw_aliases.append(value)
    return normalize_alias_list(raw_aliases)


class LegalSourceAliasService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def sync_obsidian_document_aliases(
        self,
        *,
        workspace_id: str,
        document_id: str,
        title: str | None,
        note_path: str,
        frontmatter: dict[str, Any],
    ) -> list[LegalSourceAlias]:
        self.db.query(LegalSourceAlias).filter(
            LegalSourceAlias.document_id == document_id,
        ).delete(synchronize_session=False)

        aliases = build_obsidian_aliases(title=title, note_path=note_path, frontmatter=frontmatter)
        source_name = _optional_string(frontmatter.get("source_name"))
        document_number = _optional_string(frontmatter.get("document_number"))
        source_url = _optional_string(frontmatter.get("source_url"))
        records = [
            LegalSourceAlias(
                workspace_id=workspace_id,
                document_id=document_id,
                alias=alias,
                normalized_alias=normalize_legal_alias(alias),
                source_name=source_name,
                document_number=document_number,
                source_url=source_url,
            )
            for alias in aliases
        ]
        self.db.add_all(records)
        return records


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
