import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.chunking import split_text


WIKI_LINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")
INLINE_TAG_PATTERN = re.compile(r"(?<!\w)#([A-Za-zА-Яа-яІіЇїЄєҐґ0-9_/-]+)")


@dataclass(frozen=True)
class ObsidianNote:
    path: str
    title: str
    body: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ObsidianChunk:
    note_path: str
    chunk_index: int
    chunk_text: str
    metadata: dict[str, Any]


class ObsidianIngestionService:
    def parse_note(self, file_path: str | Path, vault_root: str | Path | None = None) -> ObsidianNote:
        path = Path(file_path)
        text = path.read_text(encoding="utf-8")
        frontmatter, body = parse_frontmatter(text)
        relative_path = _relative_path(path, Path(vault_root) if vault_root else path.parent)
        inline_tags = extract_inline_tags(body)
        frontmatter_tags = normalize_tags(frontmatter.get("tags"))
        return ObsidianNote(
            path=relative_path,
            title=str(frontmatter.get("title") or path.stem),
            body=normalize_markdown_body(body),
            frontmatter=frontmatter,
            tags=sorted(set(frontmatter_tags + inline_tags)),
            links=extract_wiki_links(body),
        )

    def parse_vault(self, vault_root: str | Path) -> list[ObsidianNote]:
        root = Path(vault_root)
        notes: list[ObsidianNote] = []
        for path in sorted(root.rglob("*.md")):
            if ".obsidian" in path.parts:
                continue
            notes.append(self.parse_note(path, root))
        return notes

    def chunk_note(
        self,
        note: ObsidianNote,
        *,
        workspace_id: str,
        user_id: str,
        chunk_size: int = 1200,
        overlap: int = 150,
    ) -> list[ObsidianChunk]:
        chunks = split_text(note.body, chunk_size=chunk_size, overlap=overlap)
        return [
            ObsidianChunk(
                note_path=note.path,
                chunk_index=index,
                chunk_text=chunk,
                metadata={
                    "source": "obsidian",
                    "workspace_id": workspace_id,
                    "user_id": user_id,
                    "note_path": note.path,
                    "title": note.title,
                    "tags": note.tags,
                    "links": note.links,
                },
            )
            for index, chunk in enumerate(chunks)
        ]


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return {}, normalized

    end_index = normalized.find("\n---\n", 4)
    if end_index == -1:
        return {}, normalized

    frontmatter_text = normalized[4:end_index]
    body = normalized[end_index + len("\n---\n") :]
    return parse_simple_yaml(frontmatter_text), body


def parse_simple_yaml(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    active_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and active_key:
            result.setdefault(active_key, []).append(_parse_scalar(line.lstrip()[2:]))
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        active_key = key.strip()
        value = value.strip()
        if not value:
            result[active_key] = []
        elif value.startswith("[") and value.endswith("]"):
            result[active_key] = [
                _parse_scalar(item.strip()) for item in value[1:-1].split(",") if item.strip()
            ]
        else:
            result[active_key] = _parse_scalar(value)
    return result


def normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [_clean_tag(value)]
    if isinstance(value, list):
        return [_clean_tag(str(item)) for item in value if str(item).strip()]
    return [_clean_tag(str(value))]


def extract_inline_tags(text: str) -> list[str]:
    return sorted({_clean_tag(match) for match in INLINE_TAG_PATTERN.findall(text)})


def extract_wiki_links(text: str) -> list[str]:
    links = []
    for raw_link in WIKI_LINK_PATTERN.findall(text):
        target = raw_link.split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            links.append(target)
    return sorted(set(links))


def normalize_markdown_body(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()


def _clean_tag(value: str) -> str:
    return value.strip().lstrip("#")


def _parse_scalar(value: str) -> Any:
    stripped = value.strip().strip('"').strip("'")
    if stripped.lower() == "true":
        return True
    if stripped.lower() == "false":
        return False
    return stripped


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
