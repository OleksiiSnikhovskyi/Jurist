from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.audit_log import AuditLog
from app.services.audit_log_service import (
    MAX_METADATA_STRING_LENGTH,
    AuditLogCommand,
    AuditLogService,
    sanitize_audit_metadata,
)


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AuditLog.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def test_record_audit_log_persists_sanitized_metadata() -> None:
    db = _session()
    try:
        audit_log = AuditLogService(db).record(
            AuditLogCommand(
                action="document.read",
                user_id="user-1",
                workspace_id="workspace-1",
                object_type="document",
                object_id="document-1",
                metadata={
                    "document_name": "claim.pdf",
                    "document_text": "confidential body",
                    "risk": "medium",
                },
            )
        )

        stored = db.get(AuditLog, audit_log.id)
        assert stored is not None
        assert stored.action == "document.read"
        assert stored.metadata_json == {"document_name": "claim.pdf", "risk": "medium"}
    finally:
        db.close()


def test_record_audit_log_can_share_existing_transaction() -> None:
    db = _session()
    try:
        audit_log = AuditLogService(db).record(
            AuditLogCommand(action="workspace.member.added", user_id="user-1"),
            commit=False,
        )

        assert audit_log.id is not None
        assert db.query(AuditLog).count() == 1
    finally:
        db.close()


def test_sanitize_audit_metadata_removes_sensitive_nested_keys() -> None:
    metadata = sanitize_audit_metadata(
        {
            "source": "api",
            "prompt": "private prompt",
            "nested": {
                "full_text": "private document",
                "status": "ok",
            },
            "items": [{"raw_text": "secret", "id": "chunk-1"}],
        }
    )

    assert metadata == {
        "source": "api",
        "nested": {"status": "ok"},
        "items": [{"id": "chunk-1"}],
    }


def test_sanitize_audit_metadata_truncates_long_strings() -> None:
    metadata = sanitize_audit_metadata({"note": "x" * (MAX_METADATA_STRING_LENGTH + 1)})

    assert metadata["note"].endswith("...[truncated]")
    assert len(metadata["note"]) == MAX_METADATA_STRING_LENGTH + len("...[truncated]")
