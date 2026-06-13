import pytest

from app.config import Settings
from app.services.embedding_service import (
    DeterministicEmbeddingProvider,
    NotConfiguredEmbeddingProvider,
    get_embedding_provider,
)


def test_deterministic_embedding_has_expected_dimensions() -> None:
    provider = DeterministicEmbeddingProvider(dimensions=8)

    embedding = provider.embed("Legal contract clause")

    assert len(embedding) == 8
    assert all(-1.0 <= value <= 1.0 for value in embedding)


def test_deterministic_embedding_is_stable_for_same_text() -> None:
    provider = DeterministicEmbeddingProvider(dimensions=16)

    assert provider.embed("Same text") == provider.embed(" Same   text ")


def test_deterministic_embedding_batch() -> None:
    provider = DeterministicEmbeddingProvider(dimensions=4)

    embeddings = provider.embed_batch(["one", "two"])

    assert len(embeddings) == 2
    assert all(len(embedding) == 4 for embedding in embeddings)


def test_get_embedding_provider_uses_settings() -> None:
    settings = Settings(embedding_provider="deterministic", embedding_dimensions=12)

    provider = get_embedding_provider(settings)

    assert isinstance(provider, DeterministicEmbeddingProvider)
    assert len(provider.embed("text")) == 12


def test_not_configured_provider_raises() -> None:
    provider = get_embedding_provider(Settings(embedding_provider="none"))

    assert isinstance(provider, NotConfiguredEmbeddingProvider)
    with pytest.raises(RuntimeError):
        provider.embed("text")


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        get_embedding_provider(Settings(embedding_provider="missing"))
