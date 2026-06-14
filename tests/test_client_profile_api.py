from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.client_profile import ClientProfile
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
            ClientProfile.__table__,
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


def _seed_workspace(db: Session) -> None:
    db.add(User(id="user-1", email="user@example.com", role="lawyer"))
    db.add(Workspace(id="workspace-1", name="Workspace", owner_id="user-1", workspace_type="case"))
    db.add(WorkspaceMember(workspace_id="workspace-1", user_id="user-1", role="lawyer"))
    db.commit()


def test_client_profile_crud_flow(client: TestClient, db_session: Session) -> None:
    _seed_workspace(db_session)

    create_response = client.post(
        "/client-profiles",
        json={
            "workspace_id": "workspace-1",
            "created_by": "user-1",
            "display_name": "ТОВ Приклад",
            "client_type": "business",
            "matter_role": "позивач",
            "interests": "Стягнути заборгованість і зберегти договірні відносини.",
            "risk_preferences": "Уникати надмірно агресивної позиції.",
        },
    )

    assert create_response.status_code == 201
    profile_id = create_response.json()["id"]

    list_response = client.get("/client-profiles/by-workspace/workspace-1?user_id=user-1")
    assert list_response.status_code == 200
    assert list_response.json()[0]["display_name"] == "ТОВ Приклад"

    patch_response = client.patch(
        f"/client-profiles/{profile_id}?user_id=user-1",
        json={"communication_preferences": "Стислий executive summary."},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["communication_preferences"] == "Стислий executive summary."

    get_response = client.get(f"/client-profiles/{profile_id}?user_id=user-1")
    assert get_response.status_code == 200
    assert get_response.json()["interests"].startswith("Стягнути")


def test_client_profile_requires_workspace_membership(client: TestClient) -> None:
    response = client.post(
        "/client-profiles",
        json={
            "workspace_id": "workspace-1",
            "created_by": "missing-user",
            "display_name": "Клієнт",
        },
    )

    assert response.status_code == 403
