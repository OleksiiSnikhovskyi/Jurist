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
