from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agents.contract_review import ContractReviewAgent, detect_contract_findings
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
                chunk_text="Оплата здійснюється авансом. Пеня за прострочення 2%.",
                score=0.9,
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


def _seed_review_case(db: Session) -> None:
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
            document_name="contract.docx",
        )
    )
    db.add(
        DocumentChunk(
            id="chunk-1",
            document_id="document-1",
            workspace_id="workspace-1",
            chunk_index=0,
            chunk_text="Оплата договору та пеня за прострочення.",
        )
    )
    db.commit()


def test_detect_contract_findings_from_chunks() -> None:
    findings = detect_contract_findings(
        [
            VectorSearchResult(
                chunk_id="chunk-1",
                document_id="document-1",
                workspace_id="workspace-1",
                chunk_index=0,
                chunk_text="Оплата, штраф, пеня, строки та розірвання договору.",
                score=1.0,
            )
        ]
    )

    categories = {finding.category for finding in findings}
    assert "Оплата" in categories
    assert "Відповідальність" in categories
    assert "Строки" in categories


def test_contract_review_agent_returns_sources_and_warnings(db_session: Session) -> None:
    _seed_review_case(db_session)

    response = ContractReviewAgent(
        db_session,
        vector_search_service=FakeVectorSearchService(),
    ).review(
        AgentQueryRequest(
            user_id="user-1",
            workspace_id="workspace-1",
            document_id="document-1",
            question="Перевір договір",
        )
    )

    assert "Загальний висновок" in response.answer
    assert "Оплата" in response.answer
    assert response.sources_used[0]["document_id"] == "document-1"
    assert {warning.code for warning in response.warnings} == {
        "human_review_required",
        "law_freshness_not_checked",
    }
    assert response.confidence_score == 0.75


def test_contract_review_agent_handles_empty_context(db_session: Session) -> None:
    _seed_review_case(db_session)

    response = ContractReviewAgent(
        db_session,
        vector_search_service=EmptyVectorSearchService(),
    ).review(
        AgentQueryRequest(
            user_id="user-1",
            workspace_id="workspace-1",
            question="Перевір договір",
        )
    )

    assert "Немає релевантних фрагментів" in response.answer
    assert response.sources_used == []
    assert response.confidence_score == 0.0


def test_contract_review_api_route(db_session: Session) -> None:
    _seed_review_case(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    try:
        response = client.post(
            "/agents/contract-review/query",
            json={
                "user_id": "user-1",
                "workspace_id": "workspace-1",
                "question": "Перевір договір",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Загальний висновок" in response.json()["answer"]
