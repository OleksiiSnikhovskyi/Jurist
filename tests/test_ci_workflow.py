from pathlib import Path


def test_ci_workflow_runs_tests_and_migrations() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "pgvector/pgvector:pg16" in workflow
    assert "alembic upgrade head" in workflow
    assert "alembic check" in workflow
    assert "pytest -q -p no:cacheprovider" in workflow
    assert "DATABASE_URL" in workflow
