import shutil
from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.obsidian_ingestion_service import (
    ObsidianIngestionService,
    extract_wiki_links,
    parse_simple_yaml,
)


@pytest.fixture()
def vault_dir() -> Generator[Path, None, None]:
    path = Path("test_uploads") / f"obsidian-{uuid4()}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_parse_simple_yaml_supports_lists_and_scalars() -> None:
    result = parse_simple_yaml(
        """
title: Contract note
private: true
tags:
  - contract
  - #litigation
aliases: [claim, pleading]
"""
    )

    assert result == {
        "title": "Contract note",
        "private": True,
        "tags": ["contract", "#litigation"],
        "aliases": ["claim", "pleading"],
    }


def test_parse_note_extracts_frontmatter_tags_and_links(vault_dir: Path) -> None:
    note_path = vault_dir / "Cases" / "Claim.md"
    note_path.parent.mkdir()
    note_path.write_text(
        """---
title: Claim strategy
tags: [civil, #contract]
aliases: [Позов, claim note]
---
# Claim
See [[Evidence Note|evidence]] and [[Law/Article 625#Interest]].
Inline #urgent tag.
""",
        encoding="utf-8",
    )

    note = ObsidianIngestionService().parse_note(note_path, vault_dir)

    assert note.path == "Cases/Claim.md"
    assert note.title == "Claim strategy"
    assert note.tags == ["civil", "contract", "urgent"]
    assert note.links == ["Evidence Note", "Law/Article 625"]
    assert note.aliases == ["Позов", "claim note"]
    assert "# Claim" in note.body


def test_parse_vault_skips_obsidian_internal_files(vault_dir: Path) -> None:
    (vault_dir / "Note.md").write_text("Visible note", encoding="utf-8")
    internal_dir = vault_dir / ".obsidian"
    internal_dir.mkdir()
    (internal_dir / "workspace.md").write_text("internal", encoding="utf-8")

    notes = ObsidianIngestionService().parse_vault(vault_dir)

    assert [note.path for note in notes] == ["Note.md"]


def test_chunk_note_preserves_obsidian_metadata(vault_dir: Path) -> None:
    note_path = vault_dir / "Note.md"
    note_path.write_text("---\ntags: [law]\n---\nAlpha beta gamma " * 20, encoding="utf-8")
    service = ObsidianIngestionService()
    note = service.parse_note(note_path, vault_dir)

    chunks = service.chunk_note(
        note,
        workspace_id="workspace-1",
        user_id="user-1",
        chunk_size=50,
        overlap=5,
    )

    assert len(chunks) > 1
    assert chunks[0].metadata["source"] == "obsidian"
    assert chunks[0].metadata["workspace_id"] == "workspace-1"
    assert chunks[0].metadata["note_path"] == "Note.md"
    assert "aliases" in chunks[0].metadata


def test_extract_wiki_links_removes_aliases_and_headers() -> None:
    links = extract_wiki_links("[[A|alias]] [[B#Header]] [[Folder/C]] [[A]]")

    assert links == ["A", "B", "Folder/C"]

