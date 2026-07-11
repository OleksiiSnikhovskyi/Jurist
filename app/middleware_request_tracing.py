from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from app.config import get_settings

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
TRACE_ID_HEADER = "X-JUR-Trace-ID"


class RequestTracingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        request_id = self._request_id(request)
        trace_id = self._trace_id(request, request_id)
        request.state.request_id = request_id
        request.state.trace_id = trace_id
        started = perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            duration_ms = self._duration_ms(started)
            self._log_request(
                request=request,
                request_id=request_id,
                trace_id=trace_id,
                status_code=status_code,
                duration_ms=duration_ms,
                failed=True,
                enabled=settings.structured_request_logging_enabled,
            )
            raise

        duration_ms = self._duration_ms(started)
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers[TRACE_ID_HEADER] = trace_id
        response.headers["X-Response-Time-Ms"] = str(duration_ms)
        self._log_request(
            request=request,
            request_id=request_id,
            trace_id=trace_id,
            status_code=status_code,
            duration_ms=duration_ms,
            failed=False,
            enabled=settings.structured_request_logging_enabled,
        )
        return response

    def _request_id(self, request: Request) -> str:
        supplied = request.headers.get(REQUEST_ID_HEADER, "").strip()
        return supplied or str(uuid4())

    def _trace_id(self, request: Request, request_id: str) -> str:
        supplied = request.headers.get(TRACE_ID_HEADER, "").strip()
        return supplied or request_id

    def _duration_ms(self, started: float) -> int:
        return max(0, round((perf_counter() - started) * 1000))

    def _log_request(
        self,
        *,
        request: Request,
        request_id: str,
        trace_id: str,
        status_code: int,
        duration_ms: int,
        failed: bool,
        enabled: bool,
    ) -> None:
        if not enabled:
            return
        payload = {
            "event": "http_request_completed",
            "request_id": request_id,
            "trace_id": trace_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "client_host": self._client_host(request),
            "failed": failed,
        }
        logger.info("http_request_completed", extra={"jur_trace": payload})

    def _client_host(self, request: Request) -> str | None:
        forwarded_for = request.headers.get("x-forwarded-for", "").split(",", maxsplit=1)[0].strip()
        if forwarded_for:
            return forwarded_for
        if request.client:
            return request.client.host
        return None
