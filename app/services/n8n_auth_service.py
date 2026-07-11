from secrets import compare_digest

from fastapi import Header, HTTPException, status

from app.config import get_settings


def _configured_n8n_api_key() -> str:
    settings = get_settings()
    jur_key = (settings.jur_n8n_api_key or "").strip()
    if jur_key:
        return jur_key
    if settings.app_env.lower() not in {"local", "test"}:
        return (settings.n8n_api_key or "").strip()
    return ""


def require_n8n_api_key(
    x_jur_n8n_api_key: str | None = Header(default=None, alias="X-JUR-N8N-API-KEY"),
    x_n8n_api_key: str | None = Header(default=None, alias="X-N8N-API-KEY"),
) -> None:
    expected = _configured_n8n_api_key()
    if not expected:
        return

    supplied = (x_jur_n8n_api_key or x_n8n_api_key or "").strip()
    if not supplied or not compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing n8n API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
