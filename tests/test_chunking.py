import pytest

from app.services.chunking import split_text


def test_split_text_returns_chunks_with_overlap() -> None:
    chunks = split_text("a " * 1000, chunk_size=100, overlap=10)

    assert len(chunks) > 1
    assert all(chunk for chunk in chunks)
    assert all(len(chunk) <= 100 for chunk in chunks)


def test_split_text_rejects_invalid_overlap() -> None:
    with pytest.raises(ValueError):
        split_text("text", chunk_size=100, overlap=100)
