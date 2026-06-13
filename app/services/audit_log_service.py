from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


SENSITIVE_METADATA_KEYS = frozenset(
    {
        "content",
        "document_text",
        "extracted_text",
        "full_text",
        "message",
        "prompt",
        "raw_text",
        "system_prompt",
        "text",
    }
)
MAX_METADATA_STRING_LENGTH = 500


@dataclass(frozen=True)
class AuditLogCommand:
    action: str
    user_id: str | None = None
    workspace_id: str | None = None
    object_type: str | None = None
    object_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AuditLogService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(self, command: AuditLogCommand, *, commit: bool = True) -> AuditLog:
        audit_log = AuditLog(
            user_id=command.user_id,
            workspace_id=command.workspace_id,
            action=command.action,
            object_type=command.object_type,
            object_id=command.object_id,
            metadata_json=sanitize_audit_metadata(command.metadata),
        )
        self.db.add(audit_log)
        if commit:
            self.db.commit()
            self.db.refresh(audit_log)
        else:
            self.db.flush()
        return audit_log


def sanitize_audit_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    return {
        key: _sanitize_value(value)
        for key, value in metadata.items()
        if key.lower() not in SENSITIVE_METADATA_KEYS
    }


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) <= MAX_METADATA_STRING_LENGTH:
            return value
        return value[:MAX_METADATA_STRING_LENGTH] + "...[truncated]"
    if isinstance(value, dict):
        return sanitize_audit_metadata(value)
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return str(value)
