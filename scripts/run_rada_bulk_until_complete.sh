#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/home/oleksii/Agent_Jurist}"
CONTAINER_NAME="${CONTAINER_NAME:-jur-rada-bulk-loop}"
LIMIT_PAGES="${LIMIT_PAGES:-25}"
SLEEP_SECONDS="${SLEEP_SECONDS:-1.5}"
CATALOG_RETRIES="${CATALOG_RETRIES:-5}"
CATALOG_RETRY_SECONDS="${CATALOG_RETRY_SECONDS:-30}"
PAUSE_BETWEEN_BATCHES="${PAUSE_BETWEEN_BATCHES:-10}"
MAX_BATCHES="${MAX_BATCHES:-0}"
CATALOG_TRANSIENT_STOP_SLEEP="${CATALOG_TRANSIENT_STOP_SLEEP:-300}"
CATALOG_TRANSIENT_STOP_MAX="${CATALOG_TRANSIENT_STOP_MAX:-20}"
LOCK_DIR="${PROJECT_DIR}/legal_sources/.rada_bulk_until_complete.lock"
LOG_DIR="${PROJECT_DIR}/logs"

cd "${PROJECT_DIR}"
mkdir -p "${LOG_DIR}"

if docker ps --format '{{.Names}}' | grep -Eq '^jur-rada-bulk'; then
  echo "Another Rada bulk backfill container is already running." >&2
  docker ps --format '{{.Names}} {{.Status}}' | grep -E '^jur-rada-bulk' >&2
  exit 2
fi

if ! mkdir "${LOCK_DIR}" 2>/dev/null; then
  echo "Rada bulk loop lock exists: ${LOCK_DIR}" >&2
  echo "Remove it only after verifying no runner/backfill process is active." >&2
  exit 2
fi
trap 'rmdir "${LOCK_DIR}" 2>/dev/null || true' EXIT

batch_no=0
transient_stop_count=0
while true; do
  batch_no=$((batch_no + 1))
  if [[ "${MAX_BATCHES}" != "0" && "${batch_no}" -gt "${MAX_BATCHES}" ]]; then
    echo "Reached MAX_BATCHES=${MAX_BATCHES}; stopping."
    break
  fi

  timestamp="$(date -u +%Y%m%d_%H%M%S)"
  result_path="${LOG_DIR}/rada_bulk_result_${timestamp}_batch_${batch_no}.json"
  echo "Starting Rada bulk batch ${batch_no}; result: ${result_path}"

  set +e
  docker run --rm \
    --name "${CONTAINER_NAME}-${batch_no}" \
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
      --catalog-retry-seconds "${CATALOG_RETRY_SECONDS}" \
      > "${result_path}"
  status=$?
  set -e

  cat "${result_path}"
  if [[ "${status}" -ne 0 ]]; then
    echo "Batch ${batch_no} failed with exit code ${status}; stopping." >&2
    exit "${status}"
  fi

  echo "Building production priority_manifest.csv"
  docker run --rm \
    --network agent_jurist_jur_internal \
    -v "${PROJECT_DIR}:/work" \
    -w /work \
    agent_jurist_agent-jurist-api:latest \
    python scripts/repair_missing_legal_source_files.py \
      --manifest legal_sources/rada_bulk_manifest.csv \
      --documents-dir legal_sources \
      --sleep-seconds "${SLEEP_SECONDS}"

  python3 scripts/build_production_priority_manifest.py \
    legal_sources/rada_bulk_manifest.csv \
    --output legal_sources/priority_manifest.csv \
    --documents-dir legal_sources \
    --summary legal_sources/priority_manifest.summary.json

  should_stop="$(python3 - "${result_path}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)

pages = int(result.get("pages_this_run") or 0)
documents = int(result.get("documents_this_run") or 0)
ok = bool(result.get("ok"))
reason = result.get("stopped_reason")

if not ok:
    print(f"stopped:{reason or 'unknown'}")
elif pages == 0 and documents == 0:
    print("complete")
else:
    print("continue")
PY
)"

  case "${should_stop}" in
    complete)
      echo "Rada catalog appears complete: the last batch found no documents."
      break
      ;;
    stopped:*)
      reason="${should_stop#stopped:}"
      case "${reason}" in
        catalog_fetch_failed:*)
          transient_stop_count=$((transient_stop_count + 1))
          if [[ "${CATALOG_TRANSIENT_STOP_MAX}" != "0" && "${transient_stop_count}" -gt "${CATALOG_TRANSIENT_STOP_MAX}" ]]; then
            echo "Backfill hit ${transient_stop_count} consecutive transient catalog failures; stopping: ${reason}" >&2
            exit 3
          fi
          echo "Backfill hit transient catalog failure ${transient_stop_count}/${CATALOG_TRANSIENT_STOP_MAX}; retrying after ${CATALOG_TRANSIENT_STOP_SLEEP}s: ${reason}" >&2
          sleep "${CATALOG_TRANSIENT_STOP_SLEEP}"
          ;;
        *)
          echo "Backfill stopped before completion: ${reason}" >&2
          exit 3
          ;;
      esac
      ;;
    continue)
      transient_stop_count=0
      echo "Batch ${batch_no} complete; continuing after ${PAUSE_BETWEEN_BATCHES}s."
      sleep "${PAUSE_BETWEEN_BATCHES}"
      ;;
    *)
      echo "Unexpected loop decision: ${should_stop}" >&2
      exit 4
      ;;
  esac
done

echo "Final state:"
cat legal_sources/rada_bulk_state.json
echo "Final priority manifest summary:"
cat legal_sources/priority_manifest.summary.json
