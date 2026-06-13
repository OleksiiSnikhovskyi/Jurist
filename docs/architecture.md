# Architecture

The application is a FastAPI service with separate layers for API routes, agent orchestration, business services, persistence models, and prompts.

```text
User / Web UI / Open WebUI
  -> FastAPI routes
  -> Legal Platform Orchestrator
  -> Specialized agents
  -> Services
  -> PostgreSQL + pgvector
  -> n8n workflows
```

The central design rule is workspace isolation. Every document chunk, opinion, search result, and audit event must be scoped to the current `workspace_id` unless it comes from the shared legal knowledge base.

## Application Layers

- `app/api`: FastAPI route handlers and HTTP-specific errors.
- `app/schemas`: Pydantic request and response contracts.
- `app/services`: Business workflows that may combine multiple models or repositories.
- `app/repositories`: Persistence-oriented database queries.
- `app/models`: SQLAlchemy ORM models and database table definitions.

Workspace operations use `WorkspaceService` over `WorkspaceRepository`. Creating a workspace also creates an owner membership, so future role checks can rely on `workspace_members` as the single membership source.

Document ingestion uses `DocumentUploadService` for file storage and metadata, `DocumentTextExtractor` for supported PDF/DOCX text extraction, and `DocumentChunkingService` to persist workspace-scoped chunks for later embeddings and vector search.

Obsidian vault ingestion parses Markdown notes into note/chunk objects for indexing. Vault notes are treated like workspace-scoped private knowledge, preserving note path, frontmatter, tags, and links as retrieval metadata.

Embedding generation is configured through `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, and `EMBEDDING_DIMENSIONS`. The default `deterministic` provider is for local development and tests only; production semantic search should use a real embedding model with the same vector dimension as the database schema.

Vector search uses `VectorSearchService` to require workspace membership, load only chunks from the requested `workspace_id`, fill missing chunk embeddings, and rank results by cosine similarity. The first implementation keeps ranking in Python for portability; PostgreSQL pgvector indexing can replace the scoring layer later without changing access-control rules.

Contract review uses `ContractReviewAgent` over workspace-filtered search results. The first implementation is deterministic and source-aware: it identifies checklist risk areas from retrieved chunks and returns warnings instead of generating definitive legal conclusions.

Legal research uses `LegalResearchAgent` over the same workspace-filtered search layer. It turns retrieved chunks into a preliminary research memo with issue categories, source references, and explicit warnings that official legal sources and current court practice must be verified before relying on the answer.

Quality control uses `QualityControlAgent` as the final deterministic gate for draft answers and legal opinions. It checks whether the draft includes source grounding, factual basis, risk language, and appropriate legal caveats, while still requiring final approval by a human lawyer.
