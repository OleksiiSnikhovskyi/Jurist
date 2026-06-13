from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.quality_control import QualityControlAgent, detect_quality_control_findings
from app.database import get_db
from app.main import app
from app.models.document import Document, DocumentChunk
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.agent_schema import AgentQueryRequest
from app.services.vector_search_service import VectorSearchCommand, VectorSearchResult


class FakeVectorSearchService:
    def search(self, command: VectorSearchCommand) -> list[VectorSearchResult]:
        return [
            VectorSearchResult(
                chunk_id="chunk-1",
                document_id="document-1",
                workspace_id=command.workspace_id,
                chunk_index=0,
                chunk_text="Договір, докази, стаття ЦК України та судова практика у матеріалах справи.",
                score=0.88,
            )
        ]


class EmptyVectorSearchService:
    def search(self, command: VectorSearchCommand) -> list[VectorSearchResult]:
        return []


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    Workspace.__table__.create(engine)
    WorkspaceMember.__table__.create(engine)
    Document.__table__.create(engine)
    DocumentChunk.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _seed_qc_case(db: Session) -> None:
    db.add(User(id="user-1", email="user@example.com", role="lawyer"))
    db.add(Workspace(id="workspace-1", name="Workspace", owner_id="user-1", workspace_type="case"))
    db.add(
        WorkspaceMember(
            id="member-1",
            workspace_id="workspace-1",
            user_id="user-1",
            role="lawyer",
        )
    )
    db.add(
        Document(
            id="document-1",
            workspace_id="workspace-1",
            uploaded_by="user-1",
            document_name="opinion.md",
        )
    )
    db.add(
        DocumentChunk(
            id="chunk-1",
            document_id="document-1",
            workspace_id="workspace-1",
            chunk_index=0,
            chunk_text="Джерела, факти, докази, ризики та актуальна судова практика.",
        )
    )
    db.commit()


def test_detect_quality_control_findings_flags_overconfidence() -> None:
    findings = detect_quality_control_findings(
        "Клієнт 100% виграє, немає ризиків.",
        [
            VectorSearchResult(
                chunk_id="chunk-1",
                document_id="document-1",
                workspace_id="workspace-1",
                chunk_index=0,
                chunk_text="Матеріали справи.",
                score=1.0,
            )
        ],
    )

    categories = {finding.category for finding in findings}
    assert "Надмірна категоричність" in categories
    assert "Джерела" in categories


def test_quality_control_agent_returns_findings_sources_and_warnings(db_session: Session) -> None:
    _seed_qc_case(db_session)

    response = QualityControlAgent(
        db_session,
        vector_search_service=FakeVectorSearchService(),
    ).review(
        AgentQueryRequest(
            user_id="user-1",
            workspace_id="workspace-1",
            document_id="document-1",
            question="Висновок: клієнт гарантовано виграє.",
        )
    )

    assert "Quality Control висновок" in response.answer
    assert "Надмірна категоричність" in response.answer
    assert response.sources_used[0]["document_id"] == "document-1"
    assert {warning.code for warning in response.warnings} == {
        "quality_gate_not_final_approval",
        "source_alignment_required",
    }
    assert response.confidence_score == 0.45


def test_quality_control_agent_handles_empty_context(db_session: Session) -> None:
    _seed_qc_case(db_session)

    response = QualityControlAgent(
        db_session,
        vector_search_service=EmptyVectorSearchService(),
    ).review(
        AgentQueryRequest(
            user_id="user-1",
            workspace_id="workspace-1",
            question="Чернетка з джерелами, фактами, доказами, ризиками та перевіркою юриста.",
        )
    )

    assert "Відсутні релевантні фрагменти" in response.answer
    assert response.sources_used == []
    assert response.confidence_score == 0.0


def test_quality_control_api_route(db_session: Session) -> None:
    _seed_qc_case(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        response = client.post(
            "/agents/quality-control/query",
            json={
                "user_id": "user-1",
                "workspace_id": "workspace-1",
                "question": "Перевір чернетку: є факти, джерела, ризики і перевірка юриста.",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Quality Control висновок" in response.json()["answer"]
