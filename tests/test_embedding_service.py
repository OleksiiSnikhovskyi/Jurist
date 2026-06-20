import pytest

from app.config import Settings
from app.services.embedding_service import (
    DeterministicEmbeddingProvider,
    NotConfiguredEmbeddingProvider,
    OllamaEmbeddingProvider,
    deserialize_embedding,
    get_embedding_provider,
    serialize_embedding,
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


def test_get_embedding_provider_supports_ollama_settings() -> None:
    provider = get_embedding_provider(
        Settings(
            embedding_provider="ollama",
            embedding_base_url="http://ollama:11434",
            embedding_model="bge-m3",
            embedding_dimensions=1024,
        )
    )

    assert isinstance(provider, OllamaEmbeddingProvider)


def test_not_configured_provider_raises() -> None:
    provider = get_embedding_provider(Settings(embedding_provider="none"))

    assert isinstance(provider, NotConfiguredEmbeddingProvider)
    with pytest.raises(RuntimeError):
        provider.embed("text")


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        get_embedding_provider(Settings(embedding_provider="missing"))


def test_ollama_embedding_provider_uses_api_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"embeddings":[[0.1,0.2,0.3],[0.4,0.5,0.6]]}'

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        captured["url"] = request.full_url
        captured["body"] = request.data.decode("utf-8")
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("app.services.embedding_service.urlopen", fake_urlopen)
    provider = OllamaEmbeddingProvider(
        base_url="http://ollama:11434",
        model="bge-m3",
        dimensions=3,
        timeout_seconds=7,
    )

    embeddings = provider.embed_batch(["one", "two"])

    assert embeddings == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert captured["url"] == "http://ollama:11434/api/embed"
    assert '"model": "bge-m3"' in captured["body"]
    assert captured["timeout"] == 7


def test_embedding_serialization_round_trip() -> None:
    serialized = serialize_embedding([0.25, -0.5, 1.0])

    assert serialized == "[0.25000000,-0.50000000,1.00000000]"
    assert deserialize_embedding(serialized) == [0.25, -0.5, 1.0]
