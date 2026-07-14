# Ukrainian Legal AI Assistant

Багатоагентна юридична AI-платформа для роботи із законодавством України, документами workspace, судовою практикою та юридичними висновками для перевірки юристом.

Система не позиціонується як заміна адвоката. Її правильна роль: готувати юридичний аналітичний матеріал для перевірки юристом.

## MVP Scope

- FastAPI backend.
- PostgreSQL 16 + pgvector через Docker Compose.
- SQLAlchemy models і Alembic migration.
- Workspace-based ізоляція приватних документів.
- Personal lawyer profile for prompt, specialization, work context, represented interests, and communication style.
- Telegram/n8n intake for text, voice, photos, scans, Word/Excel/PDF documents, client profiles, and package processing.
- Production RAG foundation with Ollama `bge-m3` embeddings and pgvector indexed search.
- Healthcheck endpoint: `GET /health`.
- Agent endpoint-заготовка: `POST /agents/orchestrator/query`.
- Абстракції для embeddings і майбутніх LLM-провайдерів.
- Базові тести для каркаса.

## Local Start

```bash
cp .env.example .env
docker compose up -d
alembic upgrade head
uvicorn app.main:app --reload
pytest
```

## Production RAG Stack

The production retrieval path is PostgreSQL/pgvector, not Python-side cosine scanning.

- Answer generation model: Ollama `qwen3:8b` on Miledy with `JUR_OLLAMA_THINK=false`; optional OpenAI `gpt-4o-mini` fallback is used when Ollama/Miledy request handling fails.
- Embedding model: Ollama `bge-m3` on Miledy via `/api/embed`.
- Embedding dimensions: `1024`.
- Chunk storage: `document_chunks.embedding vector(1024)`.
- Search indexes: HNSW cosine index for embeddings plus btree/trigram indexes for workspace, document, and legal-source lookup.
- Obsidian role: curated notes, tags, links, and aliases; runtime search remains PostgreSQL/pgvector.

Production embedding env:

```bash
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=bge-m3
EMBEDDING_BASE_URL=http://100.100.209.24:11434
EMBEDDING_TIMEOUT_SECONDS=120
EMBEDDING_DIMENSIONS=1024
```

Optional answer-generation fallback env:

```bash
JUR_OPENAI_API_KEY=<server-side-api-key>
JUR_OPENAI_FALLBACK_ENABLED=true
JUR_OPENAI_FALLBACK_BASE_URL=https://api.openai.com/v1
JUR_OPENAI_FALLBACK_MODEL=gpt-4o-mini
JUR_OPENAI_FALLBACK_TIMEOUT_SECONDS=120
JUR_OPENAI_FALLBACK_MAX_TOKENS=3072
```

The fallback is implemented in the FastAPI answer service, so existing n8n/Telegram workflows continue calling the same `/n8n/...` endpoints. The fallback does not replace `bge-m3` embeddings and does not affect Rada ingestion/enrichment workflows that call Ollama directly.

After applying the `20260620_0006` migration, old deterministic embeddings are cleared and chunks must be re-embedded:

```bash
python scripts/reembed_document_chunks.py \
  --batch-size 16 \
  --state legal_sources/reembed_state.json \
  --sleep-seconds 0.2
```

On Markiz, the current background container name is:

```bash
jur-reembed-bge-m3
```

Useful monitoring commands:

```bash
docker logs -f jur-reembed-bge-m3
cat /home/oleksii/Agent_Jurist/legal_sources/reembed_state.json
docker exec agent-jurist-postgres psql -U jur_user -d jur_db -Atc \
  "select count(*) filter (where embedding is null), count(*) filter (where embedding is not null), count(*) from document_chunks"
```

## n8n Workflows

Workflow names should start with `JUR_` so they are easy to identify in n8n.

- `JUR_Bot_Intake_Queue`: Telegram bot intake, client/profile menus, package processing, auto-processing for single documents/messages.
- `JUR_Document_Processing_Start`: package/document processing helper workflow.
- `JUR_Obsidian_Vault_Sync`: selected Obsidian note sync into workspace-scoped search.
- `JUR_Rada_Law_Sync_Qwen`: Rada source sync/enrichment workflow.

Optional Rada fetch relay for IP separation via Miledy:

```bash
JUR_RADA_FETCH_RELAY_URL=http://100.100.209.24:8031/fetch
JUR_RADA_FETCH_RELAY_TOKEN=<shared-random-token>
```

The relay script is `scripts/rada_fetch_relay.py`; it allows only `https://zakon.rada.gov.ua/...` URLs and is not a general proxy.

Telegram package answers include timing metadata in `n8n_intake_packages.metadata`, including vector search time, Ollama time, prompt/context size, and total processing time.

## Project Layout

```text
app/
  api/        FastAPI routes
  agents/     Orchestrator and legal agents
  models/     SQLAlchemy models
  schemas/    Pydantic schemas
  services/   Business services and provider interfaces
  prompts/    System prompts for legal agents
docs/         Developer documentation
migrations/   Alembic migrations
n8n/          Workflow templates and notes
tests/        Pytest tests
TOR/          Original technical assignment
```

## Safety Principles

- Legal answers must be source-aware.
- Current legislation and case law must be checked before substantive conclusions.
- Private workspace documents must never be used across workspaces.
- Unverified sources must be marked as requiring verification.
- No fake statutes, cases, document details, or legal certainty.
- Official legal corpus priority: `zakon.rada.gov.ua`, courts, Cabinet, ministries, NERC, DBN/DSTU, and other official sources.
