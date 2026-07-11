import logging

from fastapi.testclient import TestClient

from app.main import app


def test_healthcheck() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "legal-ai-assistant"}


def test_request_tracing_headers_and_structured_log(caplog) -> None:
    client = TestClient(app)
    caplog.set_level(logging.INFO, logger="app.middleware_request_tracing")

    response = client.get("/health", headers={"X-Request-ID": "request-test-1"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-test-1"
    assert response.headers["X-JUR-Trace-ID"] == "request-test-1"
    assert int(response.headers["X-Response-Time-Ms"]) >= 0
    traces = [record.jur_trace for record in caplog.records if hasattr(record, "jur_trace")]
    assert traces
    trace = traces[-1]
    assert trace["event"] == "http_request_completed"
    assert trace["request_id"] == "request-test-1"
    assert trace["trace_id"] == "request-test-1"
    assert trace["method"] == "GET"
    assert trace["path"] == "/health"
    assert trace["status_code"] == 200
    assert "body" not in trace
    assert "text" not in trace
