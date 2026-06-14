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

Expected current migration after Telegram binding support is `20260614_0003`.

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
- `last_checked_at` or `checked_at`
- `topic_tags` or `tags`
- `summary`

Supported source files are `.pdf`, `.docx`, `.txt`, and `.md`. The script writes both `legal_sources` metadata and workspace-scoped `documents`/`document_chunks`.

For production legal sources, prepare the manifest before ingestion:

```bash
py -3 scripts/prepare_priority_legal_source_manifest.py legal_sources/raw_sources.csv --output legal_sources/priority_manifest.csv
py -3 scripts/ingest_legal_sources.py legal_sources/ua_laws --manifest legal_sources/priority_manifest.csv
```

The priority manifest keeps only records that can be tied to official sources and later loaded into PostgreSQL/pgvector. Use this source taxonomy:

- `constitution`: Конституція України.
- `code`: Кодекси України.
- `law`: Закони України.
- `cabinet_resolution`: Постанови Кабінету Міністрів України.
- `executive_regulation`: нормативні акти центральних органів виконавчої влади.
- `nerc_decision`: рішення та постанови НКРЕКП.
- `dbn`: ДБН.
- `dstu`: ДСТУ.
- `state_explanation`: роз'яснення державних органів.
- `supreme_court_position`: огляди та правові позиції Верховного Суду.

Approved official domains are `zakon.rada.gov.ua`, `court.gov.ua`, `supreme.court.gov.ua`, `kmu.gov.ua`, `me.gov.ua`, `minjust.gov.ua`, and `nerc.gov.ua`. Rows from news sites, private legal blogs, forums, unofficial comments, obsolete revisions, or duplicates should be excluded before ingestion. The prepared manifest must contain title, number where applicable, adoption date, current official source URL, last-check date, and thematic tags.

Suggested external storage layout for Google Drive, GitHub, or Nextcloud:

```text
legal_sources/
  priority_manifest.csv
  constitution/
  codes/
  laws/
  cabinet/
  executive/
  nerc/
  dbn/
  dstu/
  state_explanations/
  supreme_court/
```

Keep source files in the folders above and make each `file_path` in `priority_manifest.csv` relative to `legal_sources/`. See `legal_sources/priority_manifest.example.csv` for the expected columns.

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
- `POST /n8n/telegram/bindings`
- `POST /n8n/intake/process`
- `POST /n8n/obsidian/sync-note`

The public API documentation in `docs/api.md` describes the payload purpose and expected behavior.

## Server Docker Deployment

The server compose file is `docker-compose.server.yml`. It runs:

- `agent-jurist-postgres`: PostgreSQL + pgvector.
- `agent-jurist-api`: FastAPI backend on internal Docker DNS name `agent-jurist-api`.

Deploy on the n8n server with:

```bash
git clone https://github.com/OleksiiSnikhovskyi/Jurist.git Agent_Jurist
cd Agent_Jurist
docker compose -f docker-compose.server.yml up -d --build
curl http://127.0.0.1:8020/health
```

The API joins the existing `n8n-docker_default` network, so n8n should use:

```text
JUR_API_BASE_URL=http://agent-jurist-api:8000
JUR_N8N_WEBHOOK_BASE_URL=https://n8n.csc-ua.tech/webhook
```

After changing n8n environment variables, recreate the n8n container and then re-check the three active `JUR_` workflows.
