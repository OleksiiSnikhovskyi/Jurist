from typing import Protocol


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        """Create an embedding for text using the configured provider."""


class NotConfiguredEmbeddingProvider:
    def embed(self, text: str) -> list[float]:
        raise RuntimeError("Embedding provider is not configured")

