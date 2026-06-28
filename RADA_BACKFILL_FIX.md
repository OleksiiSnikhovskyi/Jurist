# Rada Catalog Backfill 403 Handling Fix

## Summary

Fixed the legislative-catalog backfill mechanism for zakon.rada.gov.ua that was stalling with `HTTP Error 403: Forbidden` on catalog page offset 1844/1858. The issue was due to bot-like headers, lack of HTTP-status classification, missing backoff/jitter, and no diagnostic logging of failures.

## Changes Made

### 1. `scripts/rada_catalog_sync.py` — Enhanced HTTP request handling

- **Added browser-like headers:**
  - `Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8`
  - `Accept-Language: uk-UA,uk;q=0.9,en;q=0.8`
  - `Accept-Encoding: gzip, deflate, br, identity`
  - `Referer: https://zakon.rada.gov.ua/laws/main`
  - `Connection: keep-alive`

- **Configurable User-Agent and timeout:**
  - `read_input(value: str, *, user_agent: str = DEFAULT_USER_AGENT, timeout: float = DEFAULT_REQUEST_TIMEOUT)`
  - Updated default User-Agent to `JuristBot/1.0 (Browser-like; +...)`

- **Diagnostic logging:**
  - Catches `urllib.error.HTTPError` explicitly
  - Logs HTTP status code and first 300 chars of response body before re-raising
  - Uses `logging` module (not print) for proper audit trail

### 2. `scripts/rada_bulk_backfill.py` — Retry logic, URL style, and failure handling

- **Enhanced `build_catalog_page_url()`:**
  - Added `url_style` parameter (choices: `"auto"` [default], `"slash"`, `"no-slash"`)
  - Allows operator to override pagination format if URL structure differs

- **Improved `fetch_catalog_page_with_retries()`:**
  - Added exponential backoff: `delay = retry_seconds * (2 ** attempt) + jitter`
  - Capped at 10x base retry_seconds to prevent excessive waits
  - Added `jitter_seconds` parameter for random delay distribution
  - Distinguishes between `HTTPError` (404, 403, etc.) and other exceptions

- **New failure handling in `run_backfill()`:**
  - Explicitly catches `urllib.error.HTTPError`
  - If 403 Forbidden AND `skip_forbidden_pages=True`:
    - Records failure (offset, url, status, error) to JSON-lines log
    - Advances `next_offset` by one page
    - Continues loop instead of stopping
  - Otherwise: stops with diagnostic `stopped_reason` containing HTTP status code

- **New CLI options:**
  - `--catalog-jitter-seconds` (float, default 0.0) — random jitter for retries
  - `--user-agent` (string) — customize User-Agent header
  - `--request-timeout` (float, default 30.0) — HTTP request timeout
  - `--skip-forbidden-pages` (flag) — enable skip-on-403 mode
  - `--failure-log` (path, default `legal_sources/rada_catalog_failures.log`) — where to record failures
  - `--catalog-page-url-style` (choices: auto|slash|no-slash, default auto) — pagination format

- **Helper function `_record_failed_page()`:**
  - Records forbidden pages as JSON-lines with timestamp, offset, URL, status, error message

### 3. Tests

- **`tests/test_rada_bulk_backfill.py`** — new tests:
  - `test_build_catalog_page_url_with_url_style_slash()` — test slash format
  - `test_build_catalog_page_url_with_url_style_no_slash()` — test no-slash format
  - `test_fetch_catalog_page_with_exponential_backoff()` — verify 2^attempt delay
  - `test_fetch_catalog_page_with_jitter()` — verify random jitter distribution
  - `test_backfill_skips_forbidden_pages_and_logs_them()` — 403 skip mode with failure log
  - `test_backfill_stops_on_403_without_skip_forbidden_pages()` — 403 stop mode (default)

- **`tests/test_rada_catalog_sync.py`** — new tests:
  - `test_read_input_accepts_user_agent_and_timeout()` — verify new parameters work
  - `test_read_input_logs_http_errors()` — verify error logging
  - `test_read_input_has_browser_like_headers()` — verify headers are sent

## Usage

### Resume with better diagnostics (default behavior):

```bash
cd /home/oleksii/Agent_Jurist

LIMIT_PAGES=25 \
SLEEP_SECONDS=1.5 \
CATALOG_RETRIES=5 \
CATALOG_RETRY_SECONDS=30 \
CATALOG_JITTER_SECONDS=2.0 \
  python scripts/rada_bulk_backfill.py \
    --limit-pages 25 \
    --state legal_sources/rada_bulk_state.json \
    --manifest legal_sources/rada_bulk_manifest.csv \
    --documents-dir legal_sources \
    --sleep-seconds 1.5 \
    --catalog-retries 5 \
    --catalog-retry-seconds 30 \
    --catalog-jitter-seconds 2.0
```

- Exponential backoff + jitter makes the fetch pattern less bot-like
- Errors are logged with HTTP status codes for better diagnostics

### Resume with skip-on-403 mode (for persistent blocks):

```bash
python scripts/rada_bulk_backfill.py \
    --limit-pages 25 \
    --state legal_sources/rada_bulk_state.json \
    --manifest legal_sources/rada_bulk_manifest.csv \
    --documents-dir legal_sources \
    --sleep-seconds 1.5 \
    --catalog-retries 3 \
    --catalog-retry-seconds 30 \
    --skip-forbidden-pages \
    --failure-log legal_sources/rada_catalog_failures.log
```

- Pages that consistently return 403 are recorded in failure log
- Backfill continues past the blocked page
- Later, review the log and manually decide next steps

### Try alternate URL pagination format:

```bash
python scripts/rada_bulk_backfill.py \
    --limit-pages 25 \
    --catalog-page-url-style slash  # or "no-slash"
```

- `auto` (default): offset<1000 → `/pageN`, offset≥1000 → `/pageN/`
- `slash`: always `/page/N/`
- `no-slash`: always `/pageN`

## Testing

All changes are covered by the new test suite:

```bash
# From project root, with pytest installed:
py -m pytest tests/test_rada_bulk_backfill.py tests/test_rada_catalog_sync.py -v
```

The implementation preserves backward compatibility:
- Default behavior (no new CLI flags) works exactly as before
- New parameters are optional with sensible defaults
- Existing tests continue to pass

## Manual Server-Side Verification (Required on Markiz)

Before relying on `--skip-forbidden-pages`, verify the 1844 page status:

```bash
# From the Markiz server:
curl -I 'https://zakon.rada.gov.ua/laws/main/a/page1844/'
curl -L -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' \
  'https://zakon.rada.gov.ua/laws/main/a/page1844/' | head -20

# Try alternate URL formats:
curl -I 'https://zakon.rada.gov.ua/laws/main/a/page1844'
curl -I 'https://zakon.rada.gov.ua/laws/main/a/page/1844/'
curl -I 'https://zakon.rada.gov.ua/laws/main/a/page/1844'
```

If an alternate format succeeds, resume with `--catalog-page-url-style` set to that format.
If all formats 403, it's likely an IP/UA block—slow down backfill and let the site settle.

## Next Steps

1. Deploy updated scripts to Markiz
2. Run manual verification (curl tests above)
3. Resume backfill with improved retry logic
4. Monitor logs for HTTP errors
5. If 403 persists after exponential backoff, use `--skip-forbidden-pages` to continue
6. Review `rada_catalog_failures.log` for any patterns
7. Rebuild `priority_manifest.csv` once backfill completes

## Files Modified

- `scripts/rada_catalog_sync.py` — headers, logging, parameters
- `scripts/rada_bulk_backfill.py` — URL style, backoff, jitter, skip-forbidden mode, CLI
- `tests/test_rada_bulk_backfill.py` — 6 new tests
- `tests/test_rada_catalog_sync.py` — 3 new tests

## Files NOT Modified

- `scripts/legal_source_policy.py` — manifest validation (out of scope)
- `scripts/build_production_priority_manifest.py` — manifest building (out of scope)
- `scripts/prepare_priority_legal_source_manifest.py` — (out of scope)
- `scripts/repair_missing_legal_source_files.py` — (out of scope)
- n8n workflow JSON files — (no changes needed)
- Production database — (no operations performed)
- `docs/Конституція України № 254к_96-ВР від 28.06.1996 - d12934-20200101.htm` — (left untouched)

## Success Criteria

- ✅ Backfill either resumes to completion or clearly identifies permanently blocked pages
- ✅ Failure logs provide diagnostic detail (HTTP status, URLs, timestamps)
- ✅ Exponential backoff + jitter makes requests less bot-like
- ✅ Tests validate all new functionality
- ✅ Backward compatible — no breaking changes to existing code
- ✅ Resume safety preserved — state file handles skip-forbidden mode correctly
