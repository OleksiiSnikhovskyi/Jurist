import hashlib
import json
from typing import Protocol

from app.config import Settings, get_settings


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        """Create an embedding for text using the configured provider."""

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Create embeddings for a batch of texts."""


class NotConfiguredEmbeddingProvider:
    def embed(self, text: str) -> list[float]:
        raise RuntimeError("Embedding provider is not configured")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("Embedding provider is not configured")


class DeterministicEmbeddingProvider:
    """Stable local embeddings for tests and development wiring.

    This is not semantically meaningful search. It gives the rest of the
    pipeline a deterministic vector-shaped value until a real provider is
    configured.
    """

    def __init__(self, dimensions: int) -> None:
        if dimensions <= 0:
            raise ValueError("Embedding dimensions must be positive")
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        normalized = " ".join(text.split()).lower()
        if not normalized:
            return [0.0] * self.dimensions

        values: list[float] = []
        seed = normalized.encode("utf-8")
        counter = 0
        while len(values) < self.dimensions:
            digest = hashlib.blake2b(seed + counter.to_bytes(4, "big"), digest_size=64).digest()
            values.extend((byte / 127.5) - 1.0 for byte in digest)
            counter += 1
        return values[: self.dimensions]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    active_settings = settings or get_settings()
    provider_name = active_settings.embedding_provider.lower()
    if provider_name == "deterministic":
        return DeterministicEmbeddingProvider(active_settings.embedding_dimensions)
    if provider_name == "none":
        return NotConfiguredEmbeddingProvider()
    raise ValueError(f"Unsupported embedding provider: {active_settings.embedding_provider}")


def serialize_embedding(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"


def deserialize_embedding(value: str | None) -> list[float] | None:
    if not value:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("Embedding value must be a list")
    return [float(item) for item in parsed]
