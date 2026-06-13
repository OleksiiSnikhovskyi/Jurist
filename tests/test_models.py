from app import models  # noqa: F401
from app.database import Base


def test_expected_tables_are_registered() -> None:
    assert {
        "users",
        "workspaces",
        "workspace_members",
        "lawyer_profiles",
        "documents",
        "legal_sources",
        "document_chunks",
        "legal_opinions",
        "audit_logs",
        "n8n_intake_packages",
        "n8n_intake_items",
    }.issubset(Base.metadata.tables.keys())
