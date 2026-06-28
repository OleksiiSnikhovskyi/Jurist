from app import models  # noqa: F401
from app.database import Base


def test_expected_tables_are_registered() -> None:
    assert {
        "users",
        "client_profiles",
        "workspaces",
        "workspace_members",
        "lawyer_profiles",
        "documents",
        "legal_sources",
        "legal_source_aliases",
        "document_chunks",
        "legal_opinions",
        "audit_logs",
        "n8n_intake_packages",
        "n8n_intake_items",
        "n8n_telegram_bindings",
    }.issubset(Base.metadata.tables.keys())

