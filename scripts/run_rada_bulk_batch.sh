#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/oleksii/Agent_Jurist}"
CONTAINER_NAME="${CONTAINER_NAME:-jur-rada-bulk-next}"
LIMIT_PAGES="${LIMIT_PAGES:-25}"
SLEEP_SECONDS="${SLEEP_SECONDS:-1.5}"
CATALOG_RETRIES="${CATALOG_RETRIES:-5}"
CATALOG_RETRY_SECONDS="${CATALOG_RETRY_SECONDS:-30}"
LOCK_DIR="${PROJECT_DIR}/legal_sources/.rada_bulk.lock"

cd "${PROJECT_DIR}"

if docker ps --format '{{.Names}}' | grep -Eq '^jur-rada-bulk'; then
  echo "Another Rada bulk backfill container is already running." >&2
  docker ps --format '{{.Names}} {{.Status}}' | grep -E '^jur-rada-bulk' >&2
  exit 2
fi

if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  echo "Rada bulk lock exists: ${LOCK_DIR}" >&2
  echo "Remove it only after verifying no jur-rada-bulk container is running." >&2
  exit 2
fi
trap 'rmdir "${LOCK_DIR}" 2>/dev/null || true' EXIT

docker run -d --rm \
  --name "${CONTAINER_NAME}" \
  --network agent_jurist_jur_internal \
  -v "${PROJECT_DIR}:/work" \
  -w /work \
  -e DATABASE_URL='postgresql+psycopg://jur_user:jur_password@agent-jurist-postgres:5432/jur_db' \
  agent_jurist_agent-jurist-api:latest \
  python scripts/rada_bulk_backfill.py \
    --limit-pages "${LIMIT_PAGES}" \
    --state /work/legal_sources/rada_bulk_state.json \
    --manifest /work/legal_sources/rada_bulk_manifest.csv \
    --documents-dir /work/legal_sources \
    --sleep-seconds "${SLEEP_SECONDS}" \
    --catalog-retries "${CATALOG_RETRIES}" \
    --catalog-retry-seconds "${CATALOG_RETRY_SECONDS}"
