import hashlib
import json
from urllib.error import URLError
from urllib.request import Request, urlopen
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


class OllamaEmbeddingProvider:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        dimensions: int,
        timeout_seconds: int,
    ) -> None:
        if not base_url:
            raise ValueError("Ollama embedding base URL is required")
        if not model:
            raise ValueError("Ollama embedding model is required")
        if dimensions <= 0:
            raise ValueError("Embedding dimensions must be positive")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.model, "input": texts}
        request = Request(
            f"{self.base_url}/api/embed",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama embedding request failed: {exc}") from exc

        embeddings = data.get("embeddings")
        if embeddings is None and isinstance(data.get("embedding"), list):
            embeddings = [data["embedding"]]
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise RuntimeError("Ollama embedding response did not match input batch size")

        normalized: list[list[float]] = []
        for embedding in embeddings:
            if not isinstance(embedding, list):
                raise RuntimeError("Ollama embedding value must be a list")
            vector = [float(value) for value in embedding]
            if len(vector) != self.dimensions:
                raise RuntimeError(
                    f"Ollama embedding dimensions mismatch: expected {self.dimensions}, got {len(vector)}"
                )
            normalized.append(vector)
        return normalized


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
    if provider_name == "ollama":
        base_url = active_settings.embedding_base_url or active_settings.jur_ollama_base_url
        if not base_url:
            return NotConfiguredEmbeddingProvider()
        return OllamaEmbeddingProvider(
            base_url=base_url,
            model=active_settings.embedding_model,
            dimensions=active_settings.embedding_dimensions,
            timeout_seconds=active_settings.embedding_timeout_seconds,
        )
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
