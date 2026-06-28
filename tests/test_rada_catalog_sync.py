import gzip
import logging
import shutil
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from scripts.prepare_priority_legal_source_manifest import prepare_manifest_rows
from scripts.rada_catalog_sync import (
    _decode_response_body,
    download_manifest_documents,
    main,
    parse_rada_arrivals_html,
    read_input,
)


@pytest.fixture()
def sync_dir() -> Generator[Path, None, None]:
    path = Path("test_uploads") / f"rada-sync-{uuid4()}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_parse_rada_arrivals_html_builds_manifest_rows() -> None:
    html = """
    <html><body>
      <ol>
        <li>
          <a href="/laws/show/4782-20">
            Про внесення зміни до статті 23 Закону України
          </a>
          Верховна Рада України; Закон від 11.02.2026 № 4782-IX
          4782-IX, Набирає чинності, 5 кб
        </li>
        <li>
          <a href="/laws/show/282-2026-%D0%BF">
            Про внесення змін до постанов Кабінету Міністрів України
          </a>
          Кабінет Міністрів України; Постанова від 25.02.2026 № 282
          282-2026-п, Чинний, 36 кб
        </li>
      </ol>
    </body></html>
    """

    rows = parse_rada_arrivals_html(html, checked_at="2026-06-14")

    assert len(rows) == 2
    assert rows[0]["source_name"] == "Про внесення зміни до статті 23 Закону України"
    assert rows[0]["source_type"] == "law"
    assert rows[0]["document_number"] == "4782-IX"
    assert rows[0]["adoption_date"] == "2026-02-11"
    assert rows[0]["validity_status"] == "pending_effective"
    assert rows[0]["source_url"] == "https://zakon.rada.gov.ua/laws/show/4782-20"
    assert rows[1]["source_type"] == "cabinet_resolution"
    assert rows[1]["validity_status"] == "current"


def test_rada_rows_pass_priority_manifest_validation() -> None:
    html = Path("tests/fixtures/rada_new_arrivals.html").read_text(encoding="utf-8")

    rows = parse_rada_arrivals_html(html, checked_at="2026-06-14")
    prepared, issues = prepare_manifest_rows(rows, today="2026-06-14")

    assert issues == []
    assert prepared[0]["source_url"].startswith("https://zakon.rada.gov.ua/laws/show/")
    assert prepared[0]["last_checked_at"] == "2026-06-14"


def test_download_manifest_documents_writes_official_html(sync_dir: Path) -> None:
    rows = [
        {
            "source_url": "https://zakon.rada.gov.ua/laws/show/4777-20",
            "file_path": "official_html/rada/4777-20.html",
        }
    ]

    counts = download_manifest_documents(
        rows,
        documents_dir=sync_dir,
        fetcher=lambda url: f"<html><body>{url}</body></html>",
    )

    target = sync_dir / "official_html" / "rada" / "4777-20.html"
    assert counts == {"downloaded": 1, "skipped": 0, "failed": 0}
    assert target.read_text(encoding="utf-8") == (
        "<html><body>https://zakon.rada.gov.ua/laws/show/4777-20</body></html>"
    )

    second_counts = download_manifest_documents(
        rows,
        documents_dir=sync_dir,
        fetcher=lambda url: "changed",
    )

    assert second_counts == {"downloaded": 0, "skipped": 1, "failed": 0}
    assert "changed" not in target.read_text(encoding="utf-8")


def test_decode_response_body_supports_gzip() -> None:
    raw = gzip.compress("Найновіші надходження".encode())

    assert _decode_response_body(raw, "gzip") == "Найновіші надходження"


def test_rada_sync_cli_does_not_fail_non_strict_on_partial_issues(
    monkeypatch: pytest.MonkeyPatch,
    sync_dir: Path,
) -> None:
    html_path = sync_dir / "arrivals.html"
    output_path = sync_dir / "manifest.csv"
    html_path.write_text(
        """
        <ol>
          <li>
            <a href="/laws/show/4777-20">Про внесення змін до Закону України</a>
            Верховна Рада України; Закон від 10.02.2026 № 4777-IX
            4777-IX, Чинний
          </li>
          <li>
            <a href="/laws/show/no-number">Про документ без номера</a>
            Верховна Рада України; Закон від 10.02.2026
            Чинний
          </li>
        </ol>
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "rada_catalog_sync.py",
            "--input",
            str(html_path),
            "--output",
            str(output_path),
            "--today",
            "2026-06-14",
        ],
    )

    main()

    manifest = output_path.read_text(encoding="utf-8")
    assert "4777-IX" in manifest
    assert "no-number" not in manifest


def test_read_input_accepts_user_agent_and_timeout() -> None:
    def mock_urlopen(request, timeout=None):
        class MockResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return b"<html></html>"

            @property
            def headers(self):
                return {}

        assert request.headers["User-Agent"] == "CustomBot/1.0"
        assert timeout == 60.0
        return MockResponse()

    with patch("scripts.rada_catalog_sync.urlopen", side_effect=mock_urlopen):
        result = read_input(
            "https://example.com",
            user_agent="CustomBot/1.0",
            timeout=60.0,
        )

    assert result == "<html></html>"


def test_read_input_logs_http_errors(caplog) -> None:
    http_error = HTTPError(
        "https://example.com/page1844/",
        403,
        "Forbidden",
        {},
        None,
    )

    def mock_urlopen(request, timeout=None):
        raise http_error

    with patch("scripts.rada_catalog_sync.urlopen", side_effect=mock_urlopen):
        with pytest.raises(HTTPError):
            with caplog.at_level(logging.ERROR):
                read_input("https://example.com/page1844/")

    assert "HTTP 403" in caplog.text
    assert "example.com/page1844" in caplog.text


def test_read_input_has_browser_like_headers() -> None:
    captured_headers = {}

    def mock_urlopen(request, timeout=None):
        captured_headers.update(request.headers)

        class MockResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return b"<html></html>"

            @property
            def headers(self):
                return {}

        return MockResponse()

    with patch("scripts.rada_catalog_sync.urlopen", side_effect=mock_urlopen):
        read_input("https://example.com")

    assert "Accept" in captured_headers
    assert "text/html" in captured_headers["Accept"]
    assert "Accept-Language" in captured_headers
    assert "uk-UA" in captured_headers["Accept-Language"]
    assert "Referer" in captured_headers
    assert "zakon.rada.gov.ua" in captured_headers["Referer"]
    assert "Connection" in captured_headers


def test_read_input_routes_rada_urls_through_relay(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}
    monkeypatch.setenv("JUR_RADA_FETCH_RELAY_URL", "http://100.100.209.24:8031/fetch")
    monkeypatch.setenv("JUR_RADA_FETCH_RELAY_TOKEN", "secret-token")

    def mock_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)

        class MockResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return b"<html></html>"

            @property
            def headers(self):
                return {}

        return MockResponse()

    with patch("scripts.rada_catalog_sync.urlopen", side_effect=mock_urlopen):
        result = read_input("https://zakon.rada.gov.ua/laws/show/503/2026")

    assert result == "<html></html>"
    assert captured["url"].startswith("http://100.100.209.24:8031/fetch?url=")
    assert "https%3A%2F%2Fzakon.rada.gov.ua%2Flaws%2Fshow%2F503%2F2026" in captured["url"]
    assert captured["headers"]["X-jur-rada-fetch-token"] == "secret-token"
