#!/usr/bin/env python3
"""Tiny allowlisted fetch relay for zakon.rada.gov.ua.

This is intentionally not a general proxy. It accepts only Rada URLs and requires
an optional shared token when JUR_RADA_FETCH_RELAY_TOKEN is configured.
"""

from __future__ import annotations

import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

ALLOWED_HOST = "zakon.rada.gov.ua"
DEFAULT_USER_AGENT = "JuristBot/0.1 (+https://github.com/OleksiiSnikhovskyi/Jurist)"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


PORT = _env_int("JUR_RADA_FETCH_RELAY_PORT", 8031)
TIMEOUT_SECONDS = _env_int("JUR_RADA_FETCH_RELAY_TIMEOUT_SECONDS", 60)
SLEEP_SECONDS = float(os.environ.get("JUR_RADA_FETCH_RELAY_SLEEP_SECONDS", "1.5"))
TOKEN = os.environ.get("JUR_RADA_FETCH_RELAY_TOKEN", "").strip()
USER_AGENT = os.environ.get("JUR_RADA_FETCH_RELAY_USER_AGENT", DEFAULT_USER_AGENT)


class RadaFetchRelay(BaseHTTPRequestHandler):
    server_version = "JurRadaFetchRelay/0.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_text(200, "ok\n")
            return
        if parsed.path != "/fetch":
            self._send_text(404, "not found\n")
            return
        if TOKEN and self.headers.get("X-JUR-RADA-FETCH-TOKEN") != TOKEN:
            self._send_text(401, "unauthorized\n")
            return

        params = parse_qs(parsed.query)
        target = (params.get("url") or [""])[0].strip()
        target_url = urlparse(target)
        if target_url.scheme != "https" or target_url.hostname != ALLOWED_HOST:
            self._send_text(400, "only https://zakon.rada.gov.ua URLs are allowed\n")
            return

        request = Request(
            target,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "uk-UA,uk;q=0.9,en;q=0.5",
                "Referer": "https://zakon.rada.gov.ua/laws/main",
            },
        )
        started = time.monotonic()
        try:
            with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                body = response.read()
                content_type = response.headers.get("Content-Type") or "text/html; charset=windows-1251"
                self.send_response(response.status)
                self.send_header("Content-Type", content_type)
                self.send_header("X-JUR-Relay-Upstream-Status", str(response.status))
                self.send_header("X-JUR-Relay-Elapsed-Ms", str(int((time.monotonic() - started) * 1000)))
                self.end_headers()
                self.wfile.write(body)
        except HTTPError as error:
            body = error.read()
            self.send_response(error.code)
            self.send_header("Content-Type", error.headers.get("Content-Type") or "text/html; charset=windows-1251")
            self.send_header("X-JUR-Relay-Upstream-Status", str(error.code))
            self.end_headers()
            self.wfile.write(body)
        except URLError as error:
            self._send_text(502, f"upstream error: {error}\n")
        finally:
            if SLEEP_SECONDS > 0:
                time.sleep(SLEEP_SECONDS)

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def _send_text(self, status: int, text: str) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), RadaFetchRelay)
    print(f"Rada fetch relay listening on 0.0.0.0:{PORT}; token_required={bool(TOKEN)}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
