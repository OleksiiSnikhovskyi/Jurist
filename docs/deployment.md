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

Supported source files are `.pdf`, `.docx`, `.xlsx`, `.html`, `.htm`, `.txt`, and `.md`. The script writes both `legal_sources` metadata and workspace-scoped `documents`/`document_chunks`.

For production legal sources, prepare the manifest before ingestion:

```bash
py -3 scripts/prepare_priority_legal_source_manifest.py legal_sources/raw_sources.csv --output legal_sources/priority_manifest.csv
py -3 scripts/ingest_legal_sources.py legal_sources/ua_laws --manifest legal_sources/priority_manifest.csv
```

For Ukrainian legislation, use the official Verkhovna Rada portal as the canonical source. The full legislation catalog is `https://zakon.rada.gov.ua/laws`; the daily newest arrivals list is `https://zakon.rada.gov.ua/laws/main/nn`.

To turn the daily arrivals page or a saved HTML export into manifest rows:

```bash
py -3 scripts/rada_catalog_sync.py --input https://zakon.rada.gov.ua/laws/main/nn --output legal_sources/rada_daily_manifest.csv
py -3 scripts/prepare_priority_legal_source_manifest.py legal_sources/rada_daily_manifest.csv --output legal_sources/priority_manifest.csv
```

When running without direct internet access, save the Rada page as HTML and pass the local file path to `--input`.

To also download the official HTML texts referenced by the daily arrivals manifest:

```bash
py -3 scripts/rada_catalog_sync.py --input https://zakon.rada.gov.ua/laws/main/nn --output legal_sources/rada_daily_manifest.csv --documents-dir legal_sources --download-documents
py -3 scripts/ingest_legal_sources.py legal_sources/official_html/rada --manifest legal_sources/rada_daily_manifest.csv
```

The downloader writes files using manifest-relative paths such as `legal_sources/official_html/rada/4777-20.html`. Existing files are skipped unless `--overwrite` is passed.
Daily Rada sync skips rows that fail priority-manifest validation and still writes valid rows. Add `--strict` when running an audit job that should fail on any invalid or incomplete source row.

The n8n template `JUR_Rada_Law_Sync_Qwen` automates the same daily-arrivals flow with local Ollama enrichment:

1. Fetch `https://zakon.rada.gov.ua/laws/main/nn`.
2. Parse official document links from the Rada page.
3. Download each document HTML in batches.
4. Ask local Ollama `qwen3:8b` only for enrichment fields: summary, thematic tags, and source-type classification.
5. Send the official text and metadata to `POST /n8n/legal-sources/upsert`.

Required n8n environment variables:

- `JUR_API_BASE_URL`: FastAPI base URL reachable from n8n.
- `JUR_KB_WORKSPACE_ID`: workspace that stores the legal corpus.
- `JUR_KB_USER_ID`: curator user used for audit logs.
- `EMBEDDING_PROVIDER`: production value `ollama`.
- `EMBEDDING_MODEL`: production value `bge-m3`.
- `EMBEDDING_BASE_URL`: Ollama HTTP API URL for embeddings, currently `http://100.100.209.24:11434`.
- `EMBEDDING_DIMENSIONS`: production value `1024`.
- `JUR_OLLAMA_BASE_URL`: Ollama HTTP API URL. On the current server, n8n and FastAPI should use the Miledy Ollama endpoint at `http://100.100.209.24:11434`.
- `JUR_OLLAMA_MODEL`: default `qwen3:8b`.
- FastAPI also uses `JUR_OLLAMA_BASE_URL`, `JUR_OLLAMA_MODEL`, `JUR_OLLAMA_TIMEOUT_SECONDS`, `JUR_OLLAMA_THINK`, `JUR_OLLAMA_NUM_CTX`, and `JUR_OLLAMA_NUM_PREDICT` for Telegram package answers. Use a long timeout, currently `900`, `JUR_OLLAMA_THINK=false`, and a context near `16384` for document packages because DOCX/OCR prompts can take several minutes on `qwen3:8b`. If `JUR_OLLAMA_BASE_URL` is unset, packages are queued but no LLM answer is generated by FastAPI.
- `JUR_RADA_SYNC_LIMIT`: safety limit for documents per run, default `3` after the first smoke run. Increase it gradually after monitoring execution time and Ollama load.

Qwen enrichment is not treated as an official source. The canonical title, URL, text, and validity metadata must come from `zakon.rada.gov.ua`; Qwen may only add tags and a short internal summary.

After switching production embeddings to `bge-m3`, run the embedding migration and then backfill chunks:

```bash
python scripts/reembed_document_chunks.py \
  --batch-size 16 \
  --state legal_sources/reembed_state.json \
  --sleep-seconds 0.2
```

The script processes only chunks with `embedding IS NULL`, writes resume state, and can be restarted safely.

For the first full corpus load, use the resumable bulk backfill runner rather than the daily n8n delta workflow. It reads the official Rada catalog page-by-page, keeps `next_offset` in a state file, appends the accepted rows to a manifest, downloads official HTML, and ingests only the current page files into PostgreSQL/chunks.

Dry-run the first two catalog pages:

```bash
py -3 scripts/rada_bulk_backfill.py --limit-pages 2 --dry-run
```

Ingest the first two pages of valid current documents:

```bash
py -3 scripts/rada_bulk_backfill.py --limit-pages 2
```

Continue the full backfill from the saved state:

```bash
py -3 scripts/rada_bulk_backfill.py
```

By default, bulk backfill ingests only rows with `validity_status=current`. Use `--include-non-current` only when building a historical archive with obsolete or pending acts. Progress is saved in `legal_sources/rada_bulk_state.json`; the cumulative manifest is `legal_sources/rada_bulk_manifest.csv`.

On the production server, start one validated 25-page batch with the guarded Docker runner:

```bash
cd /home/oleksii/Agent_Jurist
bash scripts/run_rada_bulk_batch.sh
```

The runner refuses to start when another `jur-rada-bulk*` container is already running. You can tune a run without editing the script:

```bash
LIMIT_PAGES=10 SLEEP_SECONDS=2 bash scripts/run_rada_bulk_batch.sh
```

To continue automatically until the Rada catalog is exhausted, use the loop runner after confirming no manual batch is running:

```bash
cd /home/oleksii/Agent_Jurist
nohup bash scripts/run_rada_bulk_until_complete.sh > logs/rada_bulk_until_complete.log 2>&1 &
```

The loop runner executes one foreground Docker batch at a time, repairs missing official HTML files referenced by the cumulative manifest, rebuilds `legal_sources/priority_manifest.csv` after every successful batch, and stops when a batch returns `pages_this_run=0` and `documents_this_run=0`. It also stops on transient catalog fetch failures such as repeated `403` so the operator can resume later without corrupting state. Useful controls:

```bash
MAX_BATCHES=3 bash scripts/run_rada_bulk_until_complete.sh
LIMIT_PAGES=10 PAUSE_BETWEEN_BATCHES=30 bash scripts/run_rada_bulk_until_complete.sh
```

Check progress:

```bash
docker ps --format '{{.Names}} {{.Status}}' | grep jur-rada-bulk || true
cat legal_sources/rada_bulk_state.json
```

After one or more batches finish, build the production priority manifest from the cumulative official export manifest:

```bash
python scripts/build_production_priority_manifest.py \
  legal_sources/rada_bulk_manifest.csv \
  --output legal_sources/priority_manifest.csv \
  --documents-dir legal_sources \
  --summary legal_sources/priority_manifest.summary.json
```

The builder validates official source policy, deduplicates rows, and writes only rows whose `file_path` exists under `legal_sources/`. If any rows have validation issues or missing files, it still writes the filtered manifest and summary, then exits non-zero so the operator can review the gap before treating the corpus as complete.

If a manifest build reports missing files after a manual batch, repair them from official URLs and rebuild:

```bash
python3 scripts/repair_missing_legal_source_files.py \
  --manifest legal_sources/rada_bulk_manifest.csv \
  --documents-dir legal_sources

python3 scripts/build_production_priority_manifest.py \
  legal_sources/rada_bulk_manifest.csv \
  --output legal_sources/priority_manifest.csv \
  --documents-dir legal_sources \
  --summary legal_sources/priority_manifest.summary.json
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
  official_html/
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
JUR_N8N_API_KEY=<shared-secret-from-secure-env>
```

After changing n8n environment variables, recreate the n8n container and then re-check the three active `JUR_` workflows.
For production, configure the same `JUR_N8N_API_KEY` value in both the Jurist API runtime and the n8n runtime. n8n sends it as `X-JUR-N8N-API-KEY` for every request to `JUR_API_BASE_URL`. `N8N_API_KEY` is accepted only as a non-local compatibility fallback when `JUR_N8N_API_KEY` is not set.
