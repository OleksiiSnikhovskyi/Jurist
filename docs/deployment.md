# Deployment

## Local Development

```bash
cp .env.example .env
docker compose up -d
py -3 -m alembic upgrade head
uvicorn app.main:app --reload
```

The backend expects PostgreSQL at `DATABASE_URL`. For Codespaces, update `.env` if port forwarding or service names differ.

n8n templates expect `JUR_API_BASE_URL` to point to this FastAPI service and `JUR_N8N_WEBHOOK_BASE_URL` to point to the public n8n webhook base URL.

On Windows, prefer `py -3 -m alembic ...` over the `alembic` console script if the script launcher returns `Access is denied`.

Default local database settings:

- database: `jur_db`
- database user: `jur_user`
- local development password: `jur_password`

If an existing PostgreSQL volume was initialized before these names were added, create them manually:

```bash
psql -U postgres -f scripts/create_jur_db.sql
```

## Local Verification

Before pushing deployment changes, run:

```bash
py -3 -m pytest -p no:cacheprovider
py -3 -m compileall app tests
py -3 -m alembic current
```

Expected current migration after n8n integration is `20260613_0002`.

## Knowledge Base Seeding

Markdown and Obsidian-style notes can be ingested into the development knowledge base with:

```bash
py -3 scripts/ingest_markdown_knowledge_base.py SPEC.md docs System_Prompts TOR
```

The script creates or reuses a development lawyer user and workspace from these variables:

- `JUR_KB_USER_ID`
- `JUR_KB_USER_EMAIL`
- `JUR_KB_USER_NAME`
- `JUR_KB_WORKSPACE_ID`
- `JUR_KB_WORKSPACE_NAME`

The default workspace is `JUR Knowledge Base`. Re-running the script is safe: documents are matched by `workspace_id` and `file_path`, then their chunks are rebuilt.

Legal source exports from NotebookLM or a local law folder can be ingested with:

```bash
py -3 scripts/ingest_legal_sources.py legal_sources/ua_laws --manifest legal_sources/sources.csv
```

The manifest is optional. Supported manifest formats are CSV and JSON. Common fields:

- `file_path`, `path`, or `filename`
- `source_name`, `title`, or `name`
- `source_url` or `url`
- `document_number` or `number`
- `adoption_date`
- `effective_date`
- `validity_status` or `status`
- `topic_tags` or `tags`
- `summary`

Supported source files are `.pdf`, `.docx`, `.txt`, and `.md`. The script writes both `legal_sources` metadata and workspace-scoped `documents`/`document_chunks`.

## Codespaces

For GitHub Codespaces:

- Set `DATABASE_URL` to the reachable PostgreSQL service or forwarded Postgres port.
- Set `JUR_API_BASE_URL` to the forwarded FastAPI URL.
- Keep `POSTGRES_PORT=5433` only when the local host maps Postgres to port `5433`; service-to-service Docker networking may use `5432`.
- Run `py -3 -m alembic upgrade head` after the database is reachable.
- Start FastAPI with `uvicorn app.main:app --host 0.0.0.0 --port 8000`.

## n8n Workflow Import

Import templates from `n8n/workflows`:

- `JUR_Bot_Intake_Queue.json`
- `JUR_Document_Processing_Start.json`
- `JUR_Obsidian_Vault_Sync.json`

After import:

- Replace `__TELEGRAM_CREDENTIAL_ID__` and `__TELEGRAM_CREDENTIAL_NAME__` with the Telegram credential in the n8n project.
- Configure n8n environment variables `JUR_API_BASE_URL` and `JUR_N8N_WEBHOOK_BASE_URL`.
- Keep workflows inactive until the FastAPI `/health` endpoint and `/n8n/...` endpoints are reachable.
- Activate only workflows whose names start with `JUR_`.

## Runtime Order

Recommended startup order:

1. Start PostgreSQL.
2. Apply Alembic migrations.
3. Start FastAPI.
4. Import or update n8n workflows.
5. Configure n8n credentials and environment variables.
6. Activate `JUR_` workflows.
7. Send a test Telegram message and verify an intake package appears in `n8n_intake_packages`.

## Current Integration Endpoints

n8n calls these FastAPI endpoints:

- `POST /n8n/intake/telegram`
- `POST /n8n/intake/process`
- `POST /n8n/obsidian/sync-note`

The public API documentation in `docs/api.md` describes the payload purpose and expected behavior.
