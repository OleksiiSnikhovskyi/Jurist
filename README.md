# Ukrainian Legal AI Assistant

Багатоагентна юридична AI-платформа для роботи із законодавством України, документами workspace, судовою практикою та юридичними висновками для перевірки юристом.

Система не позиціонується як заміна адвоката. Її правильна роль: готувати юридичний аналітичний матеріал для перевірки юристом.

## MVP Scope

- FastAPI backend.
- PostgreSQL 16 + pgvector через Docker Compose.
- SQLAlchemy models і Alembic migration.
- Workspace-based ізоляція приватних документів.
- Personal lawyer profile for prompt, specialization, work context, represented interests, and communication style.
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
