from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.legal_research import LegalResearchAgent, detect_legal_research_issues
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
                chunk_text=(
                    "Стаття ЦК України регулює позовну давність. "
                    "Є постанова Верховного Суду щодо доказів виконання договору."
                ),
                score=0.92,
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


def _seed_research_case(db: Session) -> None:
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
            document_name="research.md",
        )
    )
    db.add(
        DocumentChunk(
            id="chunk-1",
            document_id="document-1",
            workspace_id="workspace-1",
            chunk_index=0,
            chunk_text="Стаття ЦК України, судова практика та докази у спорі.",
        )
    )
    db.commit()


def test_detect_legal_research_issues_from_chunks() -> None:
    issues = detect_legal_research_issues(
        [
            VectorSearchResult(
                chunk_id="chunk-1",
                document_id="document-1",
                workspace_id="workspace-1",
                chunk_index=0,
                chunk_text="Закон, стаття, постанова суду, позовна давність і докази.",
                score=1.0,
            )
        ]
    )

    categories = {issue.category for issue in issues}
    assert "Норма права" in categories
    assert "Судова практика" in categories
    assert "Строки" in categories
    assert "Докази" in categories


def test_legal_research_agent_returns_sources_and_warnings(db_session: Session) -> None:
    _seed_research_case(db_session)

    response = LegalResearchAgent(
        db_session,
        vector_search_service=FakeVectorSearchService(),
    ).research(
        AgentQueryRequest(
            user_id="user-1",
            workspace_id="workspace-1",
            document_id="document-1",
            question="Яка позовна давність за договором?",
        )
    )

    assert "Попередня відповідь" in response.answer
    assert "Правові питання" in response.answer
    assert "Норма права" in response.answer
    assert response.sources_used[0]["document_id"] == "document-1"
    assert {warning.code for warning in response.warnings} == {
        "official_sources_required",
        "not_final_legal_opinion",
    }
    assert response.confidence_score == 0.7


def test_legal_research_agent_handles_empty_context(db_session: Session) -> None:
    _seed_research_case(db_session)

    response = LegalResearchAgent(
        db_session,
        vector_search_service=EmptyVectorSearchService(),
    ).research(
        AgentQueryRequest(
            user_id="user-1",
            workspace_id="workspace-1",
            question="Яка практика Верховного Суду?",
        )
    )

    assert "Немає релевантних фрагментів" in response.answer
    assert response.sources_used == []
    assert response.confidence_score == 0.0


def test_legal_research_api_route(db_session: Session) -> None:
    _seed_research_case(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        response = client.post(
            "/agents/legal-research/query",
            json={
                "user_id": "user-1",
                "workspace_id": "workspace-1",
                "question": "Знайди правову позицію",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Попередня відповідь" in response.json()["answer"]
