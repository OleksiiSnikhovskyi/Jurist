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
        "legal_source_verifications",
        "document_chunks",
        "legal_opinions",
        "legal_opinion_exports",
        "official_source_search_runs",
        "audit_logs",
        "n8n_intake_packages",
        "n8n_intake_items",
        "n8n_telegram_bindings",
    }.issubset(Base.metadata.tables.keys())
