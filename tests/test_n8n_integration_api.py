from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.document import Document, DocumentChunk
from app.models.lawyer_profile import LawyerProfile
from app.models.n8n_intake import N8nIntakeItem, N8nIntakePackage, N8nTelegramBinding
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
            LawyerProfile.__table__,
            Document.__table__,
            DocumentChunk.__table__,
            AuditLog.__table__,
            N8nIntakePackage.__table__,
            N8nIntakeItem.__table__,
            N8nTelegramBinding.__table__,
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
    db.add(
        WorkspaceMember(
            id="member-1",
            workspace_id="workspace-1",
            user_id="user-1",
            role="lawyer",
        )
    )
    db.commit()


def _seed_lawyer_profile(db: Session) -> None:
    db.add(
        LawyerProfile(
            id="profile-1",
            user_id="user-1",
            system_prompt="Працюй як український юрист з договірного права.",
            specialization="Договірне право",
        )
    )
    db.commit()


def test_telegram_intake_requires_workspace_binding(client: TestClient) -> None:
    response = client.post(
        "/n8n/intake/telegram",
        json={
            "chat_id": "100",
            "telegram_user_id": "200",
            "text": "Додати фото або документ",
            "action": "add_material",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert "прив'язати Telegram" in payload["reply_text"]


def test_telegram_intake_creates_pending_package(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)

    response = client.post(
        "/n8n/intake/telegram",
        json={
            "chat_id": "100",
            "telegram_user_id": "200",
            "workspace_id": "workspace-1",
            "user_id": "user-1",
            "action": "add_material",
            "attachments": [
                {
                    "type": "document",
                    "file_id": "telegram-file-1",
                    "file_name": "contract.docx",
                    "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                }
            ],
            "has_attachments": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["status"] == "pending"
    assert payload["item_count"] == 1
    assert db_session.query(N8nIntakePackage).count() == 1
    assert db_session.query(N8nIntakeItem).count() == 1


def test_telegram_binding_allows_intake_without_payload_identity(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)

    binding_response = client.post(
        "/n8n/telegram/bindings",
        json={
            "telegram_user_id": "200",
            "telegram_chat_id": "100",
            "username": "lawyer",
            "workspace_id": "workspace-1",
            "user_id": "user-1",
        },
    )

    assert binding_response.status_code == 200
    assert binding_response.json()["is_active"] is True

    response = client.post(
        "/n8n/intake/telegram",
        json={
            "chat_id": "100",
            "telegram_user_id": "200",
            "text": "Факти справи",
            "action": "free_text",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["item_count"] == 1
    package = db_session.query(N8nIntakePackage).one()
    assert package.workspace_id == "workspace-1"
    assert package.user_id == "user-1"


def test_bound_telegram_user_without_profile_is_asked_for_activity_direction(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    db_session.add(
        N8nTelegramBinding(
            telegram_user_id="200",
            telegram_chat_id="100",
            workspace_id="workspace-1",
            user_id="user-1",
            is_active=True,
        )
    )
    db_session.commit()

    response = client.post(
        "/n8n/intake/telegram",
        json={"chat_id": "100", "telegram_user_id": "200", "action": "add_material"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "Який напрямок Вашої діяльності" in payload["reply_text"]
    assert db_session.query(N8nIntakePackage).count() == 0
    binding = db_session.query(N8nTelegramBinding).one()
    assert binding.metadata_json["onboarding_state"] == "awaiting_activity_direction"


def test_activity_direction_text_creates_lawyer_profile(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    db_session.add(
        N8nTelegramBinding(
            telegram_user_id="200",
            telegram_chat_id="100",
            workspace_id="workspace-1",
            user_id="user-1",
            is_active=True,
            metadata_json={"onboarding_state": "awaiting_activity_direction"},
        )
    )
    db_session.commit()

    response = client.post(
        "/n8n/intake/telegram",
        json={
            "chat_id": "100",
            "telegram_user_id": "200",
            "text": "Працюю з господарськими спорами та представляю бізнес.",
            "action": "free_text",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "Профіль створено" in payload["reply_text"]
    profile = db_session.query(LawyerProfile).filter_by(user_id="user-1").one()
    assert "господарськими спорами" in profile.system_prompt
    assert "господарськими спорами" in profile.specialization


def test_edit_profile_prompt_updates_existing_lawyer_profile(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    db_session.add(
        N8nTelegramBinding(
            telegram_user_id="200",
            telegram_chat_id="100",
            workspace_id="workspace-1",
            user_id="user-1",
            is_active=True,
        )
    )
    db_session.commit()

    first_response = client.post(
        "/n8n/intake/telegram",
        json={
            "chat_id": "100",
            "telegram_user_id": "200",
            "text": "Змінити системний промпт",
            "action": "edit_profile_prompt",
        },
    )
    assert first_response.status_code == 200
    assert "Надішліть новий системний промпт" in first_response.json()["reply_text"]

    update_response = client.post(
        "/n8n/intake/telegram",
        json={
            "chat_id": "100",
            "telegram_user_id": "200",
            "text": "Я адвокат у сфері податкових спорів, відповідай стисло.",
            "action": "free_text",
        },
    )

    assert update_response.status_code == 200
    assert "Системний промпт оновлено" in update_response.json()["reply_text"]
    profile = db_session.query(LawyerProfile).filter_by(user_id="user-1").one()
    assert profile.system_prompt == "Я адвокат у сфері податкових спорів, відповідай стисло."


def test_inactive_telegram_binding_is_ignored(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    db_session.add(
        N8nTelegramBinding(
            telegram_user_id="200",
            telegram_chat_id="100",
            workspace_id="workspace-1",
            user_id="user-1",
            is_active=False,
        )
    )
    db_session.commit()

    response = client.post(
        "/n8n/intake/telegram",
        json={"chat_id": "100", "telegram_user_id": "200", "text": "Факти справи"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert db_session.query(N8nIntakePackage).count() == 0


def test_start_package_processing_marks_package_requested(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    package = N8nIntakePackage(
        id="package-1",
        workspace_id="workspace-1",
        user_id="user-1",
        channel="telegram",
        external_chat_id="100",
        status="queued",
    )
    db_session.add(package)
    db_session.add(N8nIntakeItem(package_id="package-1", item_type="text", text="Факти справи"))
    db_session.commit()

    response = client.post(
        "/n8n/intake/process",
        json={
            "package_id": "package-1",
            "requested_agent": "legal_research",
            "question": "Опрацюй матеріали",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["status"] == "processing_requested"
    assert payload["item_count"] == 1
    db_session.refresh(package)
    assert package.requested_agent == "legal_research"


def test_obsidian_sync_note_creates_document_and_chunks(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)

    response = client.post(
        "/n8n/obsidian/sync-note",
        json={
            "workspace_id": "workspace-1",
            "user_id": "user-1",
            "note_path": "cases/case-1.md",
            "title": "Case 1",
            "markdown": "Факти справи.\n\nПравова позиція та докази.",
            "tags": ["case", "contract"],
            "links": ["Related Note"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["chunk_count"] == 1
    document = db_session.get(Document, payload["document_id"])
    assert document is not None
    assert document.document_type == "obsidian_markdown"
    assert document.file_path == "obsidian://cases/case-1.md"
    assert db_session.query(DocumentChunk).filter_by(document_id=document.id).count() == 1
