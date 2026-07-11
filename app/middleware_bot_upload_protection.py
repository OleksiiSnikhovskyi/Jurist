from __future__ import annotations

from collections import defaultdict, deque
from time import monotonic

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.config import get_settings

BOT_UPLOAD_PATHS = frozenset(
    {
        "/n8n/intake/telegram",
        "/n8n/intake/extracted-text",
    }
)


class BotUploadProtectionMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method.upper() != "POST" or request.url.path not in BOT_UPLOAD_PATHS:
            return await call_next(request)

        settings = get_settings()
        payload_limit = max(0, settings.n8n_bot_payload_limit_bytes)
        if payload_limit:
            content_length = request.headers.get("content-length")
            if content_length and self._content_length_exceeds_limit(content_length, payload_limit):
                return self._payload_too_large(payload_limit)
            body = await request.body()
            if len(body) > payload_limit:
                return self._payload_too_large(payload_limit)

        retry_after = self._rate_limited_after(request)
        if retry_after is not None:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many bot upload requests"},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)

    def _content_length_exceeds_limit(self, content_length: str, payload_limit: int) -> bool:
        try:
            return int(content_length) > payload_limit
        except ValueError:
            return False

    def _rate_limited_after(self, request: Request) -> int | None:
        settings = get_settings()
        max_requests = max(0, settings.n8n_bot_rate_limit_requests)
        window_seconds = max(1, settings.n8n_bot_rate_limit_window_seconds)
        if not max_requests:
            return None

        now = monotonic()
        key = self._rate_limit_key(request)
        bucket = self._requests[key]
        cutoff = now - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= max_requests:
            retry_after = max(1, int(window_seconds - (now - bucket[0])))
            return retry_after
        bucket.append(now)
        return None

    def _rate_limit_key(self, request: Request) -> str:
        forwarded_for = request.headers.get("x-forwarded-for", "").split(",", maxsplit=1)[0].strip()
        client_host = forwarded_for or (request.client.host if request.client else "unknown")
        return f"{client_host}:{request.url.path}"

    def _payload_too_large(self, payload_limit: int) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content={
                "detail": "Bot upload payload is too large",
                "limit_bytes": payload_limit,
            },
        )
