from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.legal_opinion import LegalOpinion
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Workspace.__table__,
            WorkspaceMember.__table__,
            LegalOpinion.__table__,
        ],
    )
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_legal_opinion_review_flow(client: TestClient, db_session: Session) -> None:
    _seed_opinion(db_session)

    list_response = client.get("/legal-opinions/by-workspace/workspace-1?user_id=reviewer-1")

    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload[0]["review_status"] == "draft"
    assert payload[0]["question"] == "Проаналізуй договір"

    review_response = client.patch(
        "/legal-opinions/opinion-1/review",
        json={
            "user_id": "reviewer-1",
            "review_status": "approved",
            "review_notes": "Погоджено після перевірки джерел.",
        },
    )

    assert review_response.status_code == 200
    reviewed = review_response.json()
    assert reviewed["review_status"] == "approved"
    assert reviewed["reviewed_by"] == "reviewer-1"
    assert reviewed["reviewed_at"] is not None
    assert reviewed["review_notes"] == "Погоджено після перевірки джерел."


def test_legal_opinion_review_requires_review_permission(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_opinion(db_session, viewer_role="viewer")

    response = client.patch(
        "/legal-opinions/opinion-1/review",
        json={"user_id": "viewer-1", "review_status": "approved"},
    )

    assert response.status_code == 403


def test_legal_opinion_get_requires_workspace_membership(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_opinion(db_session)

    response = client.get("/legal-opinions/opinion-1?user_id=missing-user")

    assert response.status_code == 403


def _seed_opinion(db: Session, *, viewer_role: str = "viewer") -> None:
    db.add_all(
        [
            User(id="owner-1", email="owner@example.com", role="lawyer"),
            User(id="reviewer-1", email="reviewer@example.com", role="lawyer"),
            User(id="viewer-1", email="viewer@example.com", role="viewer"),
        ]
    )
    db.add(Workspace(id="workspace-1", name="Workspace", owner_id="owner-1", workspace_type="case"))
    db.add_all(
        [
            WorkspaceMember(workspace_id="workspace-1", user_id="owner-1", role="owner"),
            WorkspaceMember(workspace_id="workspace-1", user_id="reviewer-1", role="reviewer"),
            WorkspaceMember(workspace_id="workspace-1", user_id="viewer-1", role=viewer_role),
        ]
    )
    db.add(
        LegalOpinion(
            id="opinion-1",
            workspace_id="workspace-1",
            user_id="owner-1",
            question="Проаналізуй договір",
            answer="Draft legal answer.",
            sources_used={"package_id": "package-1"},
            review_status="draft",
        )
    )
    db.commit()
