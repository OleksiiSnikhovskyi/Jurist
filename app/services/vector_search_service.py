import math
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.document import DocumentChunk
from app.repositories.document_repository import DocumentRepository
from app.services.access_control import AccessControlService, WorkspacePermission
from app.services.embedding_service import (
    EmbeddingProvider,
    deserialize_embedding,
    get_embedding_provider,
    serialize_embedding,
)


@dataclass(frozen=True)
class VectorSearchCommand:
    workspace_id: str
    user_id: str
    query: str
    limit: int = 5


@dataclass(frozen=True)
class VectorSearchResult:
    chunk_id: str
    document_id: str
    workspace_id: str
    chunk_index: int
    chunk_text: str
    score: float


class VectorSearchService:
    def __init__(
        self,
        db: Session,
        document_repository: DocumentRepository | None = None,
        access_control: AccessControlService | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.db = db
        self.document_repository = document_repository or DocumentRepository(db)
        self.access_control = access_control or AccessControlService(db)
        self.embedding_provider = embedding_provider or get_embedding_provider()

    def search(self, command: VectorSearchCommand) -> list[VectorSearchResult]:
        self.access_control.require_permission(
            workspace_id=command.workspace_id,
            user_id=command.user_id,
            permission=WorkspacePermission.READ,
        )
        if command.limit <= 0:
            return []

        query_embedding = self.embedding_provider.embed(command.query)
        chunks = self.document_repository.list_chunks_for_workspace(command.workspace_id)
        scored_results = [
            self._score_chunk(chunk, query_embedding)
            for chunk in chunks
            if chunk.chunk_text.strip()
        ]
        scored_results.sort(key=lambda result: result.score, reverse=True)
        self.db.commit()
        return scored_results[: command.limit]

    def _score_chunk(
        self,
        chunk: DocumentChunk,
        query_embedding: list[float],
    ) -> VectorSearchResult:
        chunk_embedding = deserialize_embedding(chunk.embedding)
        if chunk_embedding is None:
            chunk_embedding = self.embedding_provider.embed(chunk.chunk_text)
            chunk.embedding = serialize_embedding(chunk_embedding)
            self.db.add(chunk)

        return VectorSearchResult(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            workspace_id=chunk.workspace_id,
            chunk_index=chunk.chunk_index,
            chunk_text=chunk.chunk_text,
            score=cosine_similarity(query_embedding, chunk_embedding),
        )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding dimensions must match")
    dot = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
