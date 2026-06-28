import math
import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.document import DocumentChunk
from app.repositories.document_repository import DocumentRepository
from app.services.legal_source_alias_service import normalize_legal_alias
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
    document_ids: list[str] | None = None
    exact_terms: list[str] | None = None


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
        if self.db.get_bind().dialect.name == "postgresql":
            return self._search_postgresql(command, query_embedding)

        chunks = self.document_repository.list_chunks_for_workspace(command.workspace_id)
        if command.document_ids:
            allowed_document_ids = set(command.document_ids)
            chunks = [chunk for chunk in chunks if chunk.document_id in allowed_document_ids]
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
            self._persist_chunk_embedding(chunk, serialize_embedding(chunk_embedding))

        return VectorSearchResult(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            workspace_id=chunk.workspace_id,
            chunk_index=chunk.chunk_index,
            chunk_text=chunk.chunk_text,
            score=cosine_similarity(query_embedding, chunk_embedding),
        )

    def _persist_chunk_embedding(self, chunk: DocumentChunk, embedding: str) -> None:
        bind = self.db.get_bind()
        if bind.dialect.name == "postgresql":
            self.db.execute(
                text("UPDATE document_chunks SET embedding = CAST(:embedding AS vector) WHERE id = :chunk_id"),
                {"embedding": embedding, "chunk_id": chunk.id},
            )
            return

        chunk.embedding = embedding
        self.db.add(chunk)

    def _search_postgresql(
        self,
        command: VectorSearchCommand,
        query_embedding: list[float],
    ) -> list[VectorSearchResult]:
        document_ids = command.document_ids or self._find_exact_document_ids(command)
        params = {
            "workspace_id": command.workspace_id,
            "query_embedding": serialize_embedding(query_embedding),
            "limit": command.limit,
        }
        document_filter = ""
        if document_ids:
            params["document_ids"] = document_ids
            document_filter = "AND dc.document_id = ANY(CAST(:document_ids AS uuid[]))"

        rows = self.db.execute(
            text(
                f"""
                SELECT
                    dc.id AS chunk_id,
                    dc.document_id AS document_id,
                    dc.workspace_id AS workspace_id,
                    dc.chunk_index AS chunk_index,
                    dc.chunk_text AS chunk_text,
                    1 - (dc.embedding <=> CAST(:query_embedding AS vector)) AS score
                FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                WHERE dc.workspace_id = :workspace_id
                  AND dc.embedding IS NOT NULL
                  AND length(trim(dc.chunk_text)) > 0
                  AND NOT EXISTS (
                    SELECT 1
                    FROM legal_sources ls
                    WHERE COALESCE(ls.validity_status, 'needs_verification') IN ('invalid', 'obsolete')
                      AND (
                        (ls.source_url IS NOT NULL AND d.file_path ILIKE '%' || ls.source_url || '%')
                        OR (ls.document_number IS NOT NULL AND d.document_name ILIKE '%' || ls.document_number || '%')
                        OR d.document_name = ls.source_name
                      )
                  )
                  {document_filter}
                ORDER BY dc.embedding <=> CAST(:query_embedding AS vector)
                LIMIT :limit
                """
            ),
            params,
        ).mappings()
        return [
            VectorSearchResult(
                chunk_id=str(row["chunk_id"]),
                document_id=str(row["document_id"]),
                workspace_id=str(row["workspace_id"]),
                chunk_index=int(row["chunk_index"]),
                chunk_text=str(row["chunk_text"]),
                score=float(row["score"]),
            )
            for row in rows
        ]
    def _find_exact_document_ids(self, command: VectorSearchCommand) -> list[str]:
        terms = command.exact_terms or extract_legal_reference_terms(command.query)
        terms = dedupe_terms([*terms, *extract_known_alias_terms(command.query)])
        if not terms:
            return []

        normalized_terms = [normalize_legal_alias(term) for term in terms]
        rows = self.db.execute(
            text(
                """
                WITH matched_aliases AS (
                    SELECT document_id, source_url, source_name, document_number
                    FROM legal_source_aliases
                    WHERE normalized_alias = ANY(CAST(:normalized_terms AS text[]))
                      AND (workspace_id IS NULL OR workspace_id = CAST(:workspace_id AS uuid))
                    LIMIT 20
                ),
                matched_sources AS (
                    SELECT source_url, source_name, document_number
                    FROM legal_sources
                    WHERE COALESCE(validity_status, 'needs_verification') NOT IN ('invalid', 'obsolete')
                      AND (
                        document_number = ANY(CAST(:terms AS text[]))
                        OR source_name = ANY(CAST(:terms AS text[]))
                        OR source_name ILIKE ANY(CAST(:like_terms AS text[]))
                      )
                    LIMIT 20
                ),
                source_matches AS (
                    SELECT source_url, source_name, document_number FROM matched_sources
                    UNION ALL
                    SELECT source_url, source_name, document_number FROM matched_aliases
                    WHERE source_url IS NOT NULL OR source_name IS NOT NULL OR document_number IS NOT NULL
                )
                SELECT DISTINCT d.id
                FROM documents d
                LEFT JOIN source_matches s
                  ON (
                    (s.source_url IS NOT NULL AND d.file_path ILIKE '%' || s.source_url || '%')
                    OR (s.document_number IS NOT NULL AND d.document_name ILIKE '%' || s.document_number || '%')
                    OR d.document_name = s.source_name
                  )
                WHERE d.workspace_id = :workspace_id
                  AND (
                    d.id IN (SELECT document_id FROM matched_aliases WHERE document_id IS NOT NULL)
                    OR s.source_url IS NOT NULL
                    OR s.source_name IS NOT NULL
                    OR s.document_number IS NOT NULL
                  )
                LIMIT 20
                """
            ),
            {
                "workspace_id": command.workspace_id,
                "terms": terms,
                "normalized_terms": normalized_terms,
                "like_terms": [f"%{term}%" for term in terms],
            },
        ).all()
        return [str(row[0]) for row in rows]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding dimensions must match")
    dot = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


LEGAL_REFERENCE_PATTERN = re.compile(
    r"\b(?:ДБН|ДСТУ)\s+[А-ЯA-Z]?[.\-\sА-ЯA-Z0-9]+:\d{4}\b|"
    r"\b\d{1,5}-[IVXІВХA-ZА-Я]{1,8}\b",
    flags=re.IGNORECASE,
)



KNOWN_LEGAL_ALIAS_PATTERN = re.compile(
    r"\b(?:ЦКУ|ГКУ|ГПК|ЦПК|КПК|ККУ|КАСУ|ПКУ|БКУ|ЗКУ|КЗпП)\b",
    flags=re.IGNORECASE,
)


def extract_known_alias_terms(text_value: str) -> list[str]:
    return dedupe_terms(match.upper() for match in KNOWN_LEGAL_ALIAS_PATTERN.findall(text_value))


def dedupe_terms(values) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = " ".join(str(value).split()).strip(" .;,")
        if not term:
            continue
        key = term.lower()
        if key in seen:
            continue
        terms.append(term)
        seen.add(key)
    return terms

def extract_legal_reference_terms(text_value: str) -> list[str]:
    terms = []
    for match in LEGAL_REFERENCE_PATTERN.findall(text_value):
        normalized = " ".join(match.split()).strip(" .;,")
        if normalized and normalized not in terms:
            terms.append(normalized)
    return terms

