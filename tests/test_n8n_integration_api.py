import logging
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.client_profile import ClientProfile
from app.models.document import Document, DocumentChunk
from app.models.lawyer_profile import LawyerProfile
from app.models.legal_opinion import LegalOpinion
from app.models.legal_source import LegalSource
from app.models.legal_source_alias import LegalSourceAlias
from app.models.legal_source_verification import LegalSourceVerification
from app.models.n8n_intake import N8nIntakeItem, N8nIntakePackage, N8nTelegramBinding
from app.models.official_source_search_run import OfficialSourceSearchRun
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.schemas.n8n_schema import N8nProcessPackageRequest
from app.services.n8n_integration_service import N8nIntegrationService
from app.services.ollama_service import (
    LegalPackageAnalysisCommand,
    LegalPackageAnalysisResult,
    SourceFragment,
)
from app.services.vector_search_service import VectorSearchCommand, VectorSearchResult


@compiles(ARRAY, "sqlite")
def _compile_pg_array_for_sqlite(type_, compiler, **kw) -> str:
    return "JSON"


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
            ClientProfile.__table__,
            Document.__table__,
            DocumentChunk.__table__,
            LegalSourceAlias.__table__,
            LegalOpinion.__table__,
            LegalSource.__table__,
            LegalSourceVerification.__table__,
            OfficialSourceSearchRun.__table__,
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


def _seed_telegram_binding(db: Session, metadata: dict | None = None) -> None:
    db.add(
        N8nTelegramBinding(
            telegram_user_id="200",
            telegram_chat_id="100",
            workspace_id="workspace-1",
            user_id="user-1",
            is_active=True,
            metadata_json=metadata,
        )
    )
    db.commit()


def _post_telegram_text(
    client: TestClient,
    text: str,
    action: str = "free_text",
) -> dict:
    response = client.post(
        "/n8n/intake/telegram",
        json={
            "chat_id": "100",
            "telegram_user_id": "200",
            "text": text,
            "action": action,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_bot_upload_payload_size_limit_returns_413(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("N8N_BOT_PAYLOAD_LIMIT_BYTES", "80")
    get_settings.cache_clear()

    try:
        response = client.post(
            "/n8n/intake/telegram",
            json={
                "chat_id": "100",
                "telegram_user_id": "200",
                "text": "x" * 500,
                "action": "free_text",
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 413
    assert response.json()["limit_bytes"] == 80


def test_bot_upload_rate_limit_returns_429(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("N8N_BOT_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("N8N_BOT_RATE_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()

    try:
        first = client.post(
            "/n8n/intake/telegram",
            headers={"X-Forwarded-For": "203.0.113.10"},
            json={
                "chat_id": "100",
                "telegram_user_id": "200",
                "text": "Питання",
                "action": "free_text",
            },
        )
        second = client.post(
            "/n8n/intake/telegram",
            headers={"X-Forwarded-For": "203.0.113.10"},
            json={
                "chat_id": "100",
                "telegram_user_id": "200",
                "text": "Ще питання",
                "action": "free_text",
            },
        )
    finally:
        get_settings.cache_clear()

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["Retry-After"]


def test_n8n_endpoints_require_api_key_when_configured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JUR_N8N_API_KEY", "jur-secret")
    get_settings.cache_clear()

    try:
        missing_header = client.post(
            "/n8n/intake/telegram",
            json={
                "chat_id": "100",
                "telegram_user_id": "200",
                "text": "Питання",
                "action": "free_text",
            },
        )
        valid_header = client.post(
            "/n8n/intake/telegram",
            headers={"X-JUR-N8N-API-KEY": "jur-secret"},
            json={
                "chat_id": "100",
                "telegram_user_id": "200",
                "text": "Питання",
                "action": "free_text",
            },
        )
    finally:
        get_settings.cache_clear()

    assert missing_header.status_code == 401
    assert valid_header.status_code == 200
    assert valid_header.json()["ok"] is False


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
                    "mime_type": (
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                }
            ],
            "has_attachments": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["status"] == "waiting_for_text_extraction"
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
    first_reply = first_response.json()["reply_text"]
    assert "Поточний системний промпт" in first_reply
    assert "Працюй як український юрист з договірного права." in first_reply
    assert "Надішліть новий системний промпт" in first_reply

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


def test_telegram_workspace_selection_switches_active_case(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    db_session.add(
        Workspace(id="workspace-2", name="Case B", owner_id="user-1", workspace_type="case")
    )
    db_session.add(
        WorkspaceMember(
            id="member-2",
            workspace_id="workspace-2",
            user_id="user-1",
            role="lawyer",
        )
    )
    db_session.add(
        ClientProfile(
            id="client-1",
            workspace_id="workspace-1",
            created_by="user-1",
            display_name="ТОВ Старий клієнт",
        )
    )
    _seed_telegram_binding(db_session, metadata={"active_client_profile_id": "client-1"})

    list_payload = _post_telegram_text(client, "Справи", "workspace_menu")

    assert "Підменю справ/workspaces" in list_payload["reply_text"]
    assert "1. Case B" in list_payload["reply_text"]
    assert "2. Workspace" in list_payload["reply_text"]

    selected_payload = _post_telegram_text(client, "1")

    assert "Активна справа: Case B" in selected_payload["reply_text"]
    binding = db_session.query(N8nTelegramBinding).one()
    assert binding.metadata_json["active_workspace_id"] == "workspace-2"
    assert "active_client_profile_id" not in binding.metadata_json


def test_telegram_intake_uses_active_workspace_from_binding_metadata(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    db_session.add(
        Workspace(id="workspace-2", name="Case B", owner_id="user-1", workspace_type="case")
    )
    db_session.add(
        WorkspaceMember(
            id="member-2",
            workspace_id="workspace-2",
            user_id="user-1",
            role="lawyer",
        )
    )
    _seed_telegram_binding(db_session, metadata={"active_workspace_id": "workspace-2"})

    payload = _post_telegram_text(client, "Факти для нової справи")

    assert payload["ok"] is True
    package = db_session.query(N8nIntakePackage).one()
    assert package.workspace_id == "workspace-2"


def test_telegram_workspace_selection_cancelled_by_main_menu(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    db_session.add(
        Workspace(id="workspace-2", name="Case B", owner_id="user-1", workspace_type="case")
    )
    db_session.add(
        WorkspaceMember(
            id="member-2",
            workspace_id="workspace-2",
            user_id="user-1",
            role="lawyer",
        )
    )
    _seed_telegram_binding(db_session)

    _post_telegram_text(client, "Справи", "workspace_menu")
    payload = _post_telegram_text(client, "Назад", "main_menu")

    assert "Головне меню" in payload["reply_text"]
    binding = db_session.query(N8nTelegramBinding).one()
    assert "workspace_selection" not in binding.metadata_json
    assert "onboarding_state" not in binding.metadata_json


def test_telegram_client_profile_onboarding_creates_active_client(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    _seed_telegram_binding(db_session)

    start_payload = _post_telegram_text(client, "Створити профіль клієнта", "create_client_profile")
    assert "ім'я або назву клієнта" in start_payload["reply_text"]

    assert "роль клієнта" in _post_telegram_text(client, "ТОВ Приклад")["reply_text"]
    assert "інтереси клієнта" in _post_telegram_text(client, "позивач")["reply_text"]
    assert (
        "ризикові побажання"
        in _post_telegram_text(
            client,
            "Стягнути борг і зберегти партнерські відносини.",
        )["reply_text"]
    )
    assert "стиль комунікації" in _post_telegram_text(client, "Обережна позиція.")["reply_text"]

    done_payload = _post_telegram_text(client, "Короткий executive summary.")
    assert "створено і зроблено активним" in done_payload["reply_text"]

    profile = db_session.query(ClientProfile).one()
    assert profile.display_name == "ТОВ Приклад"
    assert profile.matter_role == "позивач"
    binding = db_session.query(N8nTelegramBinding).one()
    assert binding.metadata_json["active_client_profile_id"] == profile.id


def test_telegram_active_client_is_attached_to_package_on_processing(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    db_session.add(
        ClientProfile(
            id="client-1",
            workspace_id="workspace-1",
            created_by="user-1",
            display_name="ТОВ Приклад",
            interests="Стягнути борг.",
        )
    )
    _seed_telegram_binding(db_session, metadata={"active_client_profile_id": "client-1"})

    response = client.post(
        "/n8n/intake/telegram",
        json={
            "chat_id": "100",
            "telegram_user_id": "200",
            "text": "Почати обробку",
            "action": "start_processing",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    package = db_session.query(N8nIntakePackage).one()
    assert package.metadata_json["client_profile_id"] == "client-1"


def test_start_processing_clears_incomplete_client_profile_draft(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    _seed_telegram_binding(
        db_session,
        metadata={
            "onboarding_state": "awaiting_client_interests",
            "client_profile_draft": {
                "display_name": "Олексій Сніховський",
                "matter_role": "Потрібно проаналізувати договір.",
            },
        },
    )

    response = client.post(
        "/n8n/intake/telegram",
        json={
            "chat_id": "100",
            "telegram_user_id": "200",
            "text": "Почати обробку",
            "action": "start_processing",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    binding = db_session.query(N8nTelegramBinding).one()
    assert binding.metadata_json == {}


def test_telegram_select_client_profile_by_number(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    db_session.add(
        ClientProfile(
            id="client-1",
            workspace_id="workspace-1",
            created_by="user-1",
            display_name="ТОВ Приклад",
        )
    )
    _seed_telegram_binding(db_session)

    list_payload = _post_telegram_text(client, "Обрати клієнта", "select_client_profile")
    assert "1. ТОВ Приклад" in list_payload["reply_text"]
    assert "ТОВ Приклад" in list_payload["reply_text"]

    selected_payload = _post_telegram_text(client, "1")
    assert "Активний клієнт: ТОВ Приклад" in selected_payload["reply_text"]
    binding = db_session.query(N8nTelegramBinding).one()
    assert binding.metadata_json["active_client_profile_id"] == "client-1"


def test_telegram_client_menu_shows_active_client(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    db_session.add(
        ClientProfile(
            id="client-1",
            workspace_id="workspace-1",
            created_by="user-1",
            display_name="ТОВ Актив",
        )
    )
    _seed_telegram_binding(db_session, metadata={"active_client_profile_id": "client-1"})

    payload = _post_telegram_text(client, "Клієнти", "client_menu")

    assert "Підменю клієнтів" in payload["reply_text"]
    assert payload["reply_menu"] == "client"
    assert "Активний клієнт: ТОВ Актив" in payload["reply_text"]
    assert "Оберіть дію кнопкою" in payload["reply_text"]


def test_telegram_client_menu_ignores_free_text_until_action_button(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    _seed_telegram_binding(db_session)

    _post_telegram_text(client, "Клієнти", "client_menu")
    payload = _post_telegram_text(client, "Створимо нового клієнта")

    assert "Ви у підменю клієнтів" in payload["reply_text"]
    assert payload["reply_menu"] == "client"
    assert db_session.query(ClientProfile).count() == 0
    assert db_session.query(N8nIntakePackage).count() == 0


def test_telegram_edit_active_client_profile_updates_existing_profile(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    db_session.add(
        ClientProfile(
            id="client-1",
            workspace_id="workspace-1",
            created_by="user-1",
            display_name="ТОВ Старий",
            matter_role="відповідач",
            interests="Зменшити суму вимог.",
        )
    )
    _seed_telegram_binding(db_session, metadata={"active_client_profile_id": "client-1"})

    start_payload = _post_telegram_text(client, "Змінити профіль клієнта", "edit_client_profile")
    assert "Поточний профіль клієнта" in start_payload["reply_text"]
    assert "ТОВ Старий" in start_payload["reply_text"]

    assert "роль клієнта" in _post_telegram_text(client, "ТОВ Новий")["reply_text"]
    assert "інтереси клієнта" in _post_telegram_text(client, "позивач")["reply_text"]
    assert (
        "ризикові побажання"
        in _post_telegram_text(client, "Стягнути заборгованість.")["reply_text"]
    )
    assert "стиль комунікації" in _post_telegram_text(client, "Готовність до суду.")["reply_text"]
    done_payload = _post_telegram_text(client, "Детальний аналіз з ризиками.")

    assert "оновлено і залишено активним" in done_payload["reply_text"]
    assert db_session.query(ClientProfile).count() == 1
    profile = db_session.get(ClientProfile, "client-1")
    assert profile is not None
    assert profile.display_name == "ТОВ Новий"
    assert profile.matter_role == "позивач"
    assert profile.interests == "Стягнути заборгованість."
    binding = db_session.query(N8nTelegramBinding).one()
    assert binding.metadata_json["active_client_profile_id"] == "client-1"


def test_telegram_delete_active_client_profile_clears_selection(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    db_session.add(
        ClientProfile(
            id="client-1",
            workspace_id="workspace-1",
            created_by="user-1",
            display_name="ТОВ Видалити",
        )
    )
    _seed_telegram_binding(db_session, metadata={"active_client_profile_id": "client-1"})

    list_payload = _post_telegram_text(client, "Видалити клієнта", "delete_client_profile")
    assert "1. ТОВ Видалити" in list_payload["reply_text"]
    assert "ТОВ Видалити" in list_payload["reply_text"]

    done_payload = _post_telegram_text(client, "1")

    assert "видалено" in done_payload["reply_text"]
    assert done_payload["reply_menu"] == "client"
    assert db_session.query(ClientProfile).count() == 0
    binding = db_session.query(N8nTelegramBinding).one()
    assert "active_client_profile_id" not in binding.metadata_json


def test_telegram_batch_start_processing_requires_review_confirmation(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    _seed_telegram_binding(db_session, metadata={"intake_mode": "batch"})
    fake_llm = FakeLegalAnalysisService()

    original_init = N8nIntegrationService.__init__

    def init_with_fake_llm(self: N8nIntegrationService, *args, **kwargs) -> None:
        kwargs["legal_analysis_service"] = fake_llm
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(N8nIntegrationService, "__init__", init_with_fake_llm)
    db_session.add(
        N8nIntakePackage(
            id="package-confirm",
            workspace_id="workspace-1",
            user_id="user-1",
            channel="telegram",
            external_chat_id="100",
            external_user_id="200",
            status="pending",
        )
    )
    db_session.add(
        N8nIntakeItem(
            package_id="package-confirm",
            item_type="document",
            file_name="contract.docx",
            text="Договір поставки з ризиком штрафу.",
        )
    )
    db_session.commit()

    first_payload = _post_telegram_text(client, "Почати обробку", "start_processing")

    assert first_payload["status"] == "pending"
    assert "Перед запуском перевірте склад пакета" in first_payload["reply_text"]
    assert "1. contract.docx" in first_payload["reply_text"]
    assert fake_llm.command is None
    package = db_session.get(N8nIntakePackage, "package-confirm")
    assert package is not None
    assert package.metadata_json["awaiting_start_confirmation"] is True

    second_payload = _post_telegram_text(client, "Почати обробку", "start_processing")

    assert second_payload["status"] == "processed"
    assert fake_llm.command is not None
    db_session.refresh(package)
    assert "awaiting_start_confirmation" not in package.metadata_json
    assert "start_confirmed_at" in package.metadata_json


def test_telegram_batch_start_processing_rejects_empty_package(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    _seed_telegram_binding(db_session, metadata={"intake_mode": "batch"})

    payload = _post_telegram_text(client, "Почати обробку", "start_processing")

    assert payload["status"] == "pending"
    assert "Пакет порожній" in payload["reply_text"]
    assert db_session.query(N8nIntakeItem).count() == 0


def test_telegram_batch_materials_are_listed_with_numbers(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    _seed_telegram_binding(db_session, metadata={"intake_mode": "batch"})

    response = client.post(
        "/n8n/intake/telegram",
        json={
            "chat_id": "100",
            "telegram_user_id": "200",
            "text": "Потрібно проаналізувати комплект",
            "action": "add_material",
            "attachments": [
                {
                    "type": "document",
                    "file_id": "telegram-file-1",
                    "file_name": "contract.docx",
                    "mime_type": (
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                },
                {
                    "type": "photo",
                    "file_id": "telegram-photo-1",
                    "file_size": 12345,
                },
            ],
            "has_attachments": True,
        },
    )
    assert response.status_code == 200

    payload = _post_telegram_text(client, "Показати додані матеріали", "list_materials")

    assert payload["reply_menu"] == "batch"
    assert "У пакеті матеріалів: 2" in payload["reply_text"]
    assert "1. contract.docx" in payload["reply_text"]
    assert "2. Фото документа" in payload["reply_text"]
    assert "Видалити матеріал 2" in payload["reply_text"]


def test_telegram_batch_material_can_be_removed_by_number(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    _seed_telegram_binding(db_session, metadata={"intake_mode": "batch"})

    db_session.add(
        N8nIntakePackage(
            id="package-1",
            workspace_id="workspace-1",
            user_id="user-1",
            channel="telegram",
            external_chat_id="100",
            external_user_id="200",
            status="pending",
        )
    )
    db_session.add_all(
        [
            N8nIntakeItem(
                id="item-1",
                package_id="package-1",
                item_type="document",
                external_file_id="telegram-file-1",
                file_name="contract.docx",
            ),
            N8nIntakeItem(
                id="item-2",
                package_id="package-1",
                item_type="voice",
                external_file_id="telegram-voice-1",
                file_name="voice.oga",
            ),
        ]
    )
    db_session.commit()

    payload = _post_telegram_text(client, "Видалити матеріал 2")

    assert payload["reply_menu"] == "batch"
    assert "Матеріал 2 видалено" in payload["reply_text"]
    assert "voice.oga" in payload["reply_text"]
    assert "1. contract.docx" in payload["reply_text"]
    assert db_session.query(N8nIntakeItem).count() == 1
    assert db_session.query(N8nIntakeItem).one().file_name == "contract.docx"


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


class FakeLegalAnalysisService:
    def __init__(self) -> None:
        self.command: LegalPackageAnalysisCommand | None = None

    def is_configured(self) -> bool:
        return True

    def analyze_package(self, command: LegalPackageAnalysisCommand) -> LegalPackageAnalysisResult:
        self.command = command
        return LegalPackageAnalysisResult(answer="LLM відповідь для юриста.", model="fake-qwen")


class FakeVectorSearchService:
    def __init__(self) -> None:
        self.command: VectorSearchCommand | None = None

    def search(self, command: VectorSearchCommand) -> list[VectorSearchResult]:
        self.command = command
        return [
            VectorSearchResult(
                chunk_id="chunk-public",
                document_id="public-source",
                workspace_id=command.workspace_id,
                chunk_index=1,
                chunk_text=(
                    "Закон України про публічні закупівлі, державного замовника і державне майно."
                ),
                score=0.91,
            ),
            VectorSearchResult(
                chunk_id="chunk-contract",
                document_id="contract-source",
                workspace_id=command.workspace_id,
                chunk_index=2,
                chunk_text=(
                    "Договір про надання послуг: істотні умови, виконання "
                    "зобов'язань, оплата і відповідальність сторін."
                ),
                score=0.87,
            ),
            VectorSearchResult(
                chunk_id="chunk-random",
                document_id="random-source",
                workspace_id=command.workspace_id,
                chunk_index=3,
                chunk_text="Порядок адміністративного погодження пропозицій органами влади.",
                score=0.81,
            ),
        ]


class FailingVectorSearchService:
    def __init__(self) -> None:
        self.command: VectorSearchCommand | None = None

    def search(self, command: VectorSearchCommand) -> list[VectorSearchResult]:
        self.command = command
        raise RuntimeError("Ollama embedding request failed: timed out")

class IncompleteLegalAnalysisService(FakeLegalAnalysisService):
    def analyze_package(self, command: LegalPackageAnalysisCommand) -> LegalPackageAnalysisResult:
        self.command = command
        return LegalPackageAnalysisResult(answer="1", model="fake-qwen")


class ClauseDraftingLegalAnalysisService(FakeLegalAnalysisService):
    def analyze_package(self, command: LegalPackageAnalysisCommand) -> LegalPackageAnalysisResult:
        self.command = command
        return LegalPackageAnalysisResult(
            answer=(
                "1. Короткий висновок\n"
                "Рекомендую додати порядок приймання та відповідальність.\n\n"
                "2. Як вставити в існуючу нумерацію\n"
                "| Куди вставити | Новий пункт | Мета |\n"
                "|---|---:|---|\n"
                "| після п. 2.3 | 2.4 | уточнити результат робіт |\n\n"
                "3. Готові формулювання пунктів\n"
                "**Пункт 2.4. Результат робіт**\n"
                '"Виконавець зобов\'язаний передати Замовнику результат робіт."\n\n'
                "4. Таблиця ризиків\n"
                "| Проблема в договорі | Ризик для клієнта | Як запропонований пункт це вирішує |\n"
                "|---|---|---|\n"
                "| немає приймання | спір щодо якості | встановлює процедуру |\n\n"
                "5. Що додатково перевірити\n"
                "- Предмет договору.\n\n"
                "6. Примітка щодо джерел\n"
                "Джерела використовуються як допоміжний контекст."
            ),
            model="fake-qwen",
        )


def test_package_source_filter_removes_public_sector_fragments_for_private_contract(
    db_session: Session,
) -> None:
    service = N8nIntegrationService(db_session)

    fragments = [
        SourceFragment(
            document_id="public-source",
            chunk_index=1,
            score=0.9,
            text="Порядок передачі об'єктів державної власності та публічні закупівлі.",
        ),
        SourceFragment(
            document_id="private-source",
            chunk_index=2,
            score=0.8,
            text="Загальні умови договору про надання послуг та виконання зобов'язань.",
        ),
    ]

    filtered = service._filter_source_fragments_for_package(
        package_text="Приватне акціонерне товариство уклало договір з фізичною особою-підприємцем.",
        fragments=fragments,
    )

    assert [fragment.document_id for fragment in filtered] == ["private-source"]


def test_package_source_filter_does_not_treat_state_building_standards_as_procurement(
    db_session: Session,
) -> None:
    service = N8nIntegrationService(db_session)

    filtered = service._filter_source_fragments_for_package(
        package_text="Документація має відповідати державним будівельним нормам і ДБН.",
        fragments=[
            SourceFragment(
                document_id="procurement-source",
                chunk_index=1,
                score=0.9,
                text="Закон України про публічні закупівлі та державного замовника.",
            )
        ],
    )

    assert filtered == []


def test_llm_answer_sanitizer_removes_procurement_when_private_contract(
    db_session: Session,
) -> None:
    service = N8nIntegrationService(db_session)

    answer = service._sanitize_answer_for_package(
        package_text="ПрАТ уклало договір з ФОП. Роботи виконуються за державними будівельними нормами.",
        answer=(
            "Договір стосується приватних сторін.\n"
            "Потрібно перевірити Закон України про публічні закупівлі.\n"
            "Варто уточнити строки приймання робіт."
        ),
    )

    assert "публічні закупівлі" not in answer
    assert "приватних сторін" in answer
    assert "строки приймання" in answer


def test_contract_clause_drafting_sanitizer_removes_empty_items_fragments_and_repeats(
    db_session: Session,
) -> None:
    service = N8nIntegrationService(db_session)

    answer = service._sanitize_answer_for_package(
        package_text="ПрАТ уклало договір з ТОВ про надання послуг.",
        answer=(
            "1. Короткий висновок\n"
            "2.\n"
            "- Уточнити порядок приймання робіт.\n"
            "- Уточнити порядок приймання робіт.\n"
            "Правова підстава: фрагмент 1.\n"
            "**Пункт 4.3. Приймання робіт**\n"
            '"Замовник має право перевірити результат робіт."'
        ),
    )

    assert "\n2.\n" not in f"\n{answer}\n"
    assert answer.count("Уточнити порядок приймання робіт") == 1
    assert "фрагмент 1" not in answer.lower()
    assert "релевантне джерело" in answer


def test_contract_clause_drafting_incomplete_check_requires_ready_clauses(
    db_session: Session,
) -> None:
    service = N8nIntegrationService(db_session)

    assert service._is_incomplete_llm_answer(
        "1. Короткий висновок\nЗагальні рекомендації.",
        "contract_clause_drafting",
    )
    assert not service._is_incomplete_llm_answer(
        "2. Як вставити в існуючу нумерацію\n"
        "| Куди вставити | Новий пункт | Мета |\n"
        "3. Готові формулювання пунктів\n"
        "**Пункт 2.4. Результат робіт**\n"
        "4. Таблиця ризиків\n"
        "| Проблема в договорі | Ризик для клієнта | Як запропонований пункт це вирішує |",
        "contract_clause_drafting",
    )


def test_telegram_continuation_note_waits_for_next_attachment(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    _seed_telegram_binding(db_session)
    fake_llm = FakeLegalAnalysisService()

    original_init = N8nIntegrationService.__init__

    def init_with_fake_llm(self: N8nIntegrationService, *args, **kwargs) -> None:
        kwargs["legal_analysis_service"] = fake_llm
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(N8nIntegrationService, "__init__", init_with_fake_llm)

    note_payload = _post_telegram_text(
        client,
        "та надати зауваження і пропозиції щодо виправлень",
    )

    assert note_payload["status"] == "pending"
    assert "Уточнення додано" in note_payload["reply_text"]
    assert fake_llm.command is None

    attachment_response = client.post(
        "/n8n/intake/telegram",
        json={
            "chat_id": "100",
            "telegram_user_id": "200",
            "text": "Потрібно проаналізувати договір",
            "action": "add_material",
            "attachments": [
                {
                    "type": "document",
                    "file_id": "telegram-file-2",
                    "file_name": "contract.docx",
                    "mime_type": (
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                }
            ],
            "has_attachments": True,
        },
    )

    assert attachment_response.status_code == 200
    attachment_payload = attachment_response.json()
    assert attachment_payload["status"] == "waiting_for_text_extraction"
    assert attachment_payload["item_count"] == 2
    assert db_session.query(N8nIntakePackage).count() == 1


def test_incomplete_llm_answer_is_not_marked_processed(db_session: Session) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    package = N8nIntakePackage(
        id="package-incomplete-llm",
        workspace_id="workspace-1",
        user_id="user-1",
        channel="telegram",
        external_chat_id="100",
        status="queued",
        question="Проаналізуй договір",
    )
    db_session.add(package)
    db_session.add(
        N8nIntakeItem(
            package_id="package-incomplete-llm",
            item_type="document",
            text="Договір про надання послуг між двома комерційними компаніями.",
        )
    )
    db_session.commit()

    response = N8nIntegrationService(
        db_session,
        legal_analysis_service=IncompleteLegalAnalysisService(),
    ).start_package_processing(
        request=N8nProcessPackageRequest(
            package_id="package-incomplete-llm",
            requested_agent="contract_review",
            question="Проаналізуй договір",
        )
    )

    assert response.status == "llm_error"
    assert response.answer is None
    assert "неповну відповідь" in response.message
    db_session.refresh(package)
    assert package.metadata_json["llm_answer_raw"] == "1"


def test_contract_followup_routes_search_to_document_facts_and_filters_sources(
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    package = N8nIntakePackage(
        id="package-contract-followup",
        workspace_id="workspace-1",
        user_id="user-1",
        channel="telegram",
        external_chat_id="100",
        status="queued",
        question="Які рекомендації щодо удосконалення цього договору? По кожному з пунктів?",
        metadata_json={"followup_source_package_id": "source-contract-package"},
    )
    source_package = N8nIntakePackage(
        id="source-contract-package",
        workspace_id="workspace-1",
        user_id="user-1",
        channel="telegram",
        external_chat_id="100",
        status="processed",
        question="Проаналізуй договір",
    )
    db_session.add_all([package, source_package])
    db_session.add(
        N8nIntakeItem(
            package_id="source-contract-package",
            item_type="document",
            text=(
                "ПрАТ Л-КАПІТАЛ уклало договір з ТОВ Виконавець про надання "
                "консультаційних послуг. Оплата здійснюється після приймання послуг."
            ),
        )
    )
    db_session.commit()
    fake_llm = FakeLegalAnalysisService()
    fake_vector = FakeVectorSearchService()

    response = N8nIntegrationService(
        db_session,
        legal_analysis_service=fake_llm,
        vector_search_service=fake_vector,
    ).start_package_processing(
        request=N8nProcessPackageRequest(
            package_id="package-contract-followup",
            requested_agent="contract_review",
            question="Які рекомендації щодо удосконалення цього договору? По кожному з пунктів?",
        )
    )

    assert response.status == "processed"
    assert fake_vector.command is not None
    assert fake_vector.command.limit == 8
    assert "ПрАТ Л-КАПІТАЛ" in fake_vector.command.query
    assert "публічні закупівлі" not in fake_vector.command.query.lower()
    assert fake_llm.command is not None
    assert [fragment.document_id for fragment in fake_llm.command.source_fragments] == [
        "contract-source"
    ]
    db_session.refresh(package)
    assert (
        package.metadata_json["processing_timings"]["query_route"] == "contract_document_followup"
    )


def test_package_processing_continues_when_vector_search_fails(
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    package = N8nIntakePackage(
        id="package-vector-fallback",
        workspace_id="workspace-1",
        user_id="user-1",
        channel="telegram",
        external_chat_id="100",
        status="queued",
    )
    db_session.add(package)
    db_session.add(
        N8nIntakeItem(
            package_id="package-vector-fallback",
            item_type="document",
            text="Договір між двома комерційними компаніями про надання послуг.",
        )
    )
    db_session.commit()
    fake_llm = FakeLegalAnalysisService()
    failing_vector = FailingVectorSearchService()

    response = N8nIntegrationService(
        db_session,
        legal_analysis_service=fake_llm,
        vector_search_service=failing_vector,
    ).start_package_processing(
        request=N8nProcessPackageRequest(
            package_id="package-vector-fallback",
            requested_agent="contract_review",
            question="Проаналізуй договір.",
        )
    )

    assert response.status == "processed"
    assert fake_llm.command is not None
    assert fake_llm.command.source_fragments == []
    db_session.refresh(package)
    timings = package.metadata_json["processing_timings"]
    assert timings["vector_result_count"] == 0
    assert timings["filtered_source_fragment_count"] == 0
    assert "Ollama embedding request failed" in timings["vector_search_error"]

def test_contract_clause_drafting_mode_activates_for_numbered_clause_request(
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    package = N8nIntakePackage(
        id="package-clause-drafting",
        workspace_id="workspace-1",
        user_id="user-1",
        channel="telegram",
        external_chat_id="100",
        status="queued",
        question="Які би ти додав пункти до договору з дотриманням існуючої нумерації?",
    )
    db_session.add(package)
    db_session.add(
        N8nIntakeItem(
            package_id="package-clause-drafting",
            item_type="document",
            text=(
                "Договір між ПрАТ Л-КАПІТАЛ як Замовником та ТОВ Виконавець "
                "про надання консультаційних послуг."
            ),
        )
    )
    db_session.commit()
    fake_llm = ClauseDraftingLegalAnalysisService()

    response = N8nIntegrationService(
        db_session,
        legal_analysis_service=fake_llm,
        vector_search_service=FakeVectorSearchService(),
    ).start_package_processing(
        request=N8nProcessPackageRequest(
            package_id="package-clause-drafting",
            requested_agent="contract_review",
            question="Які би ти додав пункти до договору з дотриманням існуючої нумерації?",
        )
    )

    assert response.status == "processed"
    assert fake_llm.command is not None
    assert fake_llm.command.response_mode == "contract_clause_drafting"
    assert "| Куди вставити | Новий пункт | Мета |" in response.answer
    db_session.refresh(package)
    assert (
        package.metadata_json["processing_timings"]["response_mode"] == "contract_clause_drafting"
    )


def test_telegram_batch_menu_keeps_materials_pending(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    _seed_telegram_binding(db_session)

    menu_payload = _post_telegram_text(client, "Пакетна обробка", "batch_processing_menu")
    assert menu_payload["reply_menu"] == "batch"
    assert "Пакетна обробка увімкнена" in menu_payload["reply_text"]

    payload = _post_telegram_text(client, "Перший документ стосується договору.")

    assert payload["reply_menu"] == "batch"
    assert payload["status"] == "pending"
    assert "Почати обробку" in payload["reply_text"]
    package = db_session.query(N8nIntakePackage).one()
    assert package.status == "pending"


def test_telegram_free_text_processes_immediately(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    _seed_telegram_binding(db_session)
    fake_llm = FakeLegalAnalysisService()

    original_init = N8nIntegrationService.__init__

    def init_with_fake_llm(self: N8nIntegrationService, *args, **kwargs) -> None:
        kwargs["legal_analysis_service"] = fake_llm
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(N8nIntegrationService, "__init__", init_with_fake_llm)

    payload = _post_telegram_text(client, "Проаналізуй умови договору поставки.")

    assert payload["status"] == "processed"
    assert payload["reply_text"] == "LLM відповідь для юриста."
    assert fake_llm.command is not None
    assert "договору поставки" in fake_llm.command.package_text


def test_telegram_followup_uses_last_processed_document_context(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    _seed_telegram_binding(db_session)
    previous = N8nIntakePackage(
        id="previous-contract-package",
        workspace_id="workspace-1",
        user_id="user-1",
        channel="telegram",
        external_chat_id="100",
        external_user_id="200",
        status="processed",
        question="Проаналізуй договір",
    )
    db_session.add(previous)
    db_session.add(
        N8nIntakeItem(
            package_id="previous-contract-package",
            item_type="document",
            file_name="contract.docx",
            text="ПрАТ Л-КАПІТАЛ уклало договір з ФОП про науково-проєктні роботи.",
        )
    )
    db_session.commit()
    fake_llm = FakeLegalAnalysisService()

    original_init = N8nIntegrationService.__init__

    def init_with_fake_llm(self: N8nIntegrationService, *args, **kwargs) -> None:
        kwargs["legal_analysis_service"] = fake_llm
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(N8nIntegrationService, "__init__", init_with_fake_llm)

    payload = _post_telegram_text(client, "Які рекомендації щодо удосконалення цього договору?")

    assert payload["status"] == "processed"
    assert fake_llm.command is not None
    assert "ПрАТ Л-КАПІТАЛ" in fake_llm.command.package_text
    assert "удосконалення цього договору" in fake_llm.command.package_text
    current_package = (
        db_session.query(N8nIntakePackage)
        .filter(N8nIntakePackage.id != "previous-contract-package")
        .one()
    )
    assert (
        current_package.metadata_json["followup_source_package_id"] == "previous-contract-package"
    )


def test_telegram_followup_resolves_previous_followup_to_original_document(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    _seed_telegram_binding(db_session)
    original = N8nIntakePackage(
        id="original-contract-package",
        workspace_id="workspace-1",
        user_id="user-1",
        channel="telegram",
        external_chat_id="100",
        external_user_id="200",
        status="processed",
        question="Проаналізуй договір",
    )
    previous_followup = N8nIntakePackage(
        id="previous-followup-package",
        workspace_id="workspace-1",
        user_id="user-1",
        channel="telegram",
        external_chat_id="100",
        external_user_id="200",
        status="processed",
        question="Що в договорі треба перевірити за ДБН?",
        metadata_json={"followup_source_package_id": "original-contract-package"},
    )
    db_session.add_all([original, previous_followup])
    db_session.add(
        N8nIntakeItem(
            package_id="original-contract-package",
            item_type="document",
            file_name="contract.docx",
            text=(
                "ПрАТ Л-КАПІТАЛ уклало договір з ФОП про розробку "
                "науково-проєктної документації на суму 944 601,75 грн."
            ),
        )
    )
    db_session.add(
        N8nIntakeItem(
            package_id="previous-followup-package",
            item_type="text",
            text="Що в договорі треба перевірити за ДБН?",
        )
    )
    db_session.commit()
    fake_llm = FakeLegalAnalysisService()

    original_init = N8nIntegrationService.__init__

    def init_with_fake_llm(self: N8nIntegrationService, *args, **kwargs) -> None:
        kwargs["legal_analysis_service"] = fake_llm
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(N8nIntegrationService, "__init__", init_with_fake_llm)

    payload = _post_telegram_text(client, "Які рекомендації щодо удосконалення цього договору?")

    assert payload["status"] == "processed"
    assert fake_llm.command is not None
    assert "944 601,75 грн" in fake_llm.command.package_text
    assert "Що в договорі треба перевірити за ДБН" not in fake_llm.command.package_text
    current_package = (
        db_session.query(N8nIntakePackage)
        .filter(
            N8nIntakePackage.id.notin_(["original-contract-package", "previous-followup-package"])
        )
        .one()
    )
    assert (
        current_package.metadata_json["followup_source_package_id"] == "original-contract-package"
    )


def test_start_package_processing_can_return_ollama_answer(
    db_session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    package = N8nIntakePackage(
        id="package-llm",
        workspace_id="workspace-1",
        user_id="user-1",
        channel="telegram",
        external_chat_id="100",
        status="queued",
        question="Проаналізуй ризики",
    )
    db_session.add(package)
    db_session.add(
        N8nIntakeItem(package_id="package-llm", item_type="text", text="Є договір поставки.")
    )
    db_session.commit()
    fake_llm = FakeLegalAnalysisService()
    caplog.set_level(logging.INFO, logger="app.services.n8n_integration_service")

    response = N8nIntegrationService(
        db_session,
        legal_analysis_service=fake_llm,
    ).start_package_processing(
        request=N8nProcessPackageRequest(
            package_id="package-llm",
            requested_agent="legal_research",
            question="Проаналізуй ризики",
        )
    )

    assert response.ok is True
    assert response.status == "processed"
    assert response.answer == "LLM відповідь для юриста."
    assert fake_llm.command is not None
    assert "договір поставки" in fake_llm.command.package_text
    db_session.refresh(package)
    assert package.metadata_json["llm_model"] == "fake-qwen"
    opinion = db_session.query(LegalOpinion).one()
    assert opinion.workspace_id == "workspace-1"
    assert opinion.user_id == "user-1"
    assert opinion.question == "Проаналізуй ризики"
    assert opinion.answer == "LLM відповідь для юриста."
    assert opinion.sources_used["package_id"] == "package-llm"
    assert opinion.sources_used["llm_model"] == "fake-qwen"
    assert package.metadata_json["legal_opinion_id"] == opinion.id
    assert package.metadata_json["processing_timings"]["source_fragment_count"] >= 0
    assert package.metadata_json["processing_timings"]["total_seconds"] >= 0
    timing_records = [
        record.jur_timing
        for record in caplog.records
        if record.message.startswith("jur.telegram_rag_processing ")
    ]
    assert timing_records
    assert timing_records[-1]["event"] == "processed"
    assert timing_records[-1]["package_id"] == "package-llm"
    assert timing_records[-1]["query_route"] == "contract_document"
    assert timing_records[-1]["response_mode"] == "legal_analysis"
    assert timing_records[-1]["model"] == "fake-qwen"
    assert timing_records[-1]["total_seconds"] >= 0


def test_start_package_processing_uses_active_telegram_client_when_not_explicit(
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    db_session.add(
        ClientProfile(
            id="client-1",
            workspace_id="workspace-1",
            created_by="user-1",
            display_name="ТОВ Активний",
            interests="Захистити покупця.",
        )
    )
    _seed_telegram_binding(db_session, metadata={"active_client_profile_id": "client-1"})
    package = N8nIntakePackage(
        id="package-active-client",
        workspace_id="workspace-1",
        user_id="user-1",
        channel="telegram",
        external_chat_id="100",
        external_user_id="200",
        status="queued",
        question="Проаналізуй ризики",
    )
    db_session.add(package)
    db_session.add(
        N8nIntakeItem(
            package_id="package-active-client", item_type="text", text="Є спір щодо поставки."
        )
    )
    db_session.commit()
    fake_llm = FakeLegalAnalysisService()

    response = N8nIntegrationService(
        db_session,
        legal_analysis_service=fake_llm,
    ).start_package_processing(
        request=N8nProcessPackageRequest(
            package_id="package-active-client",
            requested_agent="legal_research",
            question="Проаналізуй ризики",
        )
    )

    assert response.status == "processed"
    assert fake_llm.command is not None
    assert fake_llm.command.client_context is not None
    assert "ТОВ Активний" in fake_llm.command.client_context
    assert "Захистити покупця" in fake_llm.command.client_context
    db_session.refresh(package)
    assert package.metadata_json["client_profile_id"] == "client-1"


def test_attach_extracted_text_indexes_telegram_attachment(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    package = N8nIntakePackage(
        id="package-extract",
        workspace_id="workspace-1",
        user_id="user-1",
        channel="telegram",
        external_chat_id="100",
        status="pending",
    )
    item = N8nIntakeItem(
        id="item-extract",
        package_id="package-extract",
        item_type="document",
        external_file_id="telegram-file-1",
        file_name="contract.pdf",
        mime_type="application/pdf",
    )
    db_session.add(package)
    db_session.add(item)
    db_session.commit()

    response = client.post(
        "/n8n/intake/extracted-text",
        json={
            "package_id": "package-extract",
            "external_file_id": "telegram-file-1",
            "extracted_text": "Текст договору поставки. Прострочення оплати 10 днів.",
            "extraction_method": "linguistproai.text_extract",
            "document_type": "telegram_pdf",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["item_id"] == "item-extract"
    assert payload["chunk_count"] == 1
    db_session.refresh(item)
    assert "Прострочення оплати" in item.text
    document = db_session.get(Document, payload["document_id"])
    assert document is not None
    assert document.file_path == "telegram://document/telegram-file-1"
    assert document.document_type == "telegram_pdf"
    assert db_session.query(DocumentChunk).filter_by(document_id=document.id).count() == 1


def test_attach_extracted_text_queues_auto_processing_without_blocking(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    package = N8nIntakePackage(
        id="package-auto-extract",
        workspace_id="workspace-1",
        user_id="user-1",
        channel="telegram",
        external_chat_id="100",
        external_user_id="200",
        status="waiting_for_text_extraction",
        metadata_json={"auto_process_after_extraction": True},
        question="Проаналізуй документ",
    )
    item = N8nIntakeItem(
        id="item-auto-extract",
        package_id="package-auto-extract",
        item_type="document",
        external_file_id="telegram-file-auto",
        file_name="contract.pdf",
    )
    db_session.add(package)
    db_session.add(item)
    db_session.commit()
    fake_llm = FakeLegalAnalysisService()

    original_init = N8nIntegrationService.__init__

    def init_with_fake_llm(self: N8nIntegrationService, *args, **kwargs) -> None:
        kwargs["legal_analysis_service"] = fake_llm
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(N8nIntegrationService, "__init__", init_with_fake_llm)

    response = client.post(
        "/n8n/intake/extracted-text",
        json={
            "package_id": "package-auto-extract",
            "external_file_id": "telegram-file-auto",
            "extracted_text": "Текст договору поставки з ризиком штрафу.",
            "extraction_method": "linguistproai.text_extract",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["answer"] is None
    assert payload["message"] == "Extracted text attached and queued for analysis."
    assert fake_llm.command is None
    db_session.refresh(package)
    assert "auto_process_after_extraction" not in package.metadata_json
    assert package.metadata_json["analysis_requested_after_extraction"] is True


def test_attach_extracted_text_can_auto_process_and_return_answer(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    package = N8nIntakePackage(
        id="package-auto-process-extract",
        workspace_id="workspace-1",
        user_id="user-1",
        channel="telegram",
        external_chat_id="100",
        external_user_id="200",
        status="waiting_for_text_extraction",
        metadata_json={"auto_process_after_extraction": True},
        requested_agent="contract_review",
        question="Проаналізуй договір після OCR",
    )
    item = N8nIntakeItem(
        id="item-auto-process-extract",
        package_id="package-auto-process-extract",
        item_type="document",
        external_file_id="telegram-file-auto-process",
        file_name="contract.pdf",
    )
    db_session.add(package)
    db_session.add(item)
    db_session.commit()
    fake_llm = FakeLegalAnalysisService()

    original_init = N8nIntegrationService.__init__

    def init_with_fake_llm(self: N8nIntegrationService, *args, **kwargs) -> None:
        kwargs["legal_analysis_service"] = fake_llm
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(N8nIntegrationService, "__init__", init_with_fake_llm)

    response = client.post(
        "/n8n/intake/extracted-text",
        json={
            "package_id": "package-auto-process-extract",
            "external_file_id": "telegram-file-auto-process",
            "extracted_text": "Текст договору поставки з ризиком штрафу.",
            "extraction_method": "linguistproai.text_extract",
            "auto_process": True,
            "requested_agent": "contract_review",
            "question": "Проаналізуй договір після OCR",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "processed"
    assert payload["answer"] == "LLM відповідь для юриста."
    assert payload["message"] == "Extracted text attached and analyzed."
    assert fake_llm.command is not None
    assert "ризиком штрафу" in fake_llm.command.package_text
    db_session.refresh(package)
    assert package.metadata_json["analysis_requested_after_extraction"] is True
    assert package.metadata_json["legal_opinion_id"]
    assert db_session.query(LegalOpinion).count() == 1


def test_start_package_processing_uses_extracted_attachment_text(
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    package = N8nIntakePackage(
        id="package-attachment-llm",
        workspace_id="workspace-1",
        user_id="user-1",
        channel="telegram",
        external_chat_id="100",
        status="queued",
        question="Проаналізуй документ",
    )
    db_session.add(package)
    db_session.add(
        N8nIntakeItem(
            package_id="package-attachment-llm",
            item_type="document",
            external_file_id="telegram-file-2",
            file_name="contract.pdf",
            text="Витягнутий текст договору з ризиком штрафу.",
        )
    )
    db_session.commit()
    fake_llm = FakeLegalAnalysisService()

    response = N8nIntegrationService(
        db_session,
        legal_analysis_service=fake_llm,
    ).start_package_processing(
        request=N8nProcessPackageRequest(
            package_id="package-attachment-llm",
            requested_agent="contract_review",
            question="Проаналізуй документ",
        )
    )

    assert response.status == "processed"
    assert fake_llm.command is not None
    assert "[document]" in fake_llm.command.package_text
    assert "ризиком штрафу" in fake_llm.command.package_text


def test_telegram_start_processing_returns_ollama_answer(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_workspace(db_session)
    _seed_lawyer_profile(db_session)
    _seed_telegram_binding(db_session)
    fake_llm = FakeLegalAnalysisService()

    original_init = N8nIntegrationService.__init__

    def init_with_fake_llm(self: N8nIntegrationService, *args, **kwargs) -> None:
        kwargs["legal_analysis_service"] = fake_llm
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(N8nIntegrationService, "__init__", init_with_fake_llm)

    _post_telegram_text(client, "Пакетна обробка", "batch_processing_menu")
    _post_telegram_text(client, "Є договір поставки з простроченням оплати.")
    first_payload = _post_telegram_text(client, "Почати обробку", "start_processing")

    assert first_payload["status"] == "pending"
    assert "Перед запуском перевірте склад пакета" in first_payload["reply_text"]
    assert fake_llm.command is None

    payload = _post_telegram_text(client, "Почати обробку", "start_processing")

    assert payload["status"] == "processed"
    assert payload["reply_text"] == "LLM відповідь для юриста."


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
            "frontmatter": {
                "aliases": ["ДБН проектна документація", "DBN A.2.2-14"],
                "document_number": "ДБН А.2.2-14:2016",
                "source_name": "ДБН А.2.2-14:2016",
            },
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
    aliases = db_session.query(LegalSourceAlias).filter_by(document_id=document.id).all()
    assert {alias.normalized_alias for alias in aliases} >= {
        "case 1",
        "case-1",
        "дбн проектна документація",
        "dbn a.2.2-14",
        "дбн а.2.2-14:2016",
    }
    assert all(alias.workspace_id == "workspace-1" for alias in aliases)


def test_reembed_missing_chunks_endpoint_embeds_new_chunks(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_workspace(db_session)
    db_session.add(
        Document(
            id="document-reembed",
            workspace_id="workspace-1",
            uploaded_by="user-1",
            document_name="law.html",
            document_type="legal_source_law",
            extracted_text="текст закону",
        )
    )
    db_session.add(
        DocumentChunk(
            id="chunk-reembed",
            document_id="document-reembed",
            workspace_id="workspace-1",
            chunk_index=0,
            chunk_text="текст закону про чинність",
        )
    )
    db_session.commit()

    monkeypatch.setenv("EMBEDDING_PROVIDER", "deterministic")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "3")

    response = client.post(
        "/n8n/maintenance/reembed-missing-chunks",
        json={"batch_size": 2, "limit": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] == 1
    assert payload["remaining_null_embeddings"] == 0
    chunk = db_session.get(DocumentChunk, "chunk-reembed")
    assert chunk is not None
    assert chunk.embedding is not None


def test_official_source_candidate_endpoint_returns_stale_official_sources(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    db_session.add(
        LegalSource(
            id="legal-source-rada",
            source_type="law",
            source_name="Закон України про тест",
            source_url="https://zakon.rada.gov.ua/laws/show/123-20",
            document_number="123-20",
            validity_status="current",
        )
    )
    db_session.add(
        LegalSource(
            id="legal-source-blog",
            source_type="law",
            source_name="Unofficial blog",
            source_url="https://example-law-blog.test/post",
            validity_status="current",
        )
    )
    db_session.commit()

    response = client.post(
        "/n8n/legal-sources/verification-candidates",
        json={"workspace_id": "workspace-1", "user_id": "user-1", "limit": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert [item["legal_source_id"] for item in payload["candidates"]] == ["legal-source-rada"]
    assert payload["candidates"][0]["source_domain"] == "zakon.rada.gov.ua"


def test_official_source_verification_endpoint_records_metadata_without_full_text(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)
    db_session.add(
        LegalSource(
            id="legal-source-verify",
            source_type="supreme_court_position",
            source_name="Огляд Верховного Суду",
            source_url="https://supreme.court.gov.ua/supreme/pres-centr/news/",
            validity_status="current",
            full_text="Canonical text stays on the legal source, not in verification metadata.",
        )
    )
    db_session.commit()

    response = client.post(
        "/n8n/legal-sources/verify-official-sources",
        json={
            "workspace_id": "workspace-1",
            "user_id": "user-1",
            "verifications": [
                {
                    "legal_source_id": "legal-source-verify",
                    "source_url": "https://supreme.court.gov.ua/supreme/pres-centr/news/",
                    "source_domain": "supreme.court.gov.ua",
                    "source_kind": "court_practice",
                    "allowlist_status": "allowed",
                    "verification_status": "verified",
                    "http_status": 200,
                    "final_url": "https://supreme.court.gov.ua/supreme/pres-centr/news/",
                    "content_type": "text/html; charset=utf-8",
                    "confidence": "high",
                    "evidence_summary": "Official source URL is reachable.",
                    "verification_payload": {"workflow": "JUR_Official_Source_Verification"},
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["processed"] == 1
    assert payload["verified"] == 1
    verification = db_session.query(LegalSourceVerification).one()
    assert verification.legal_source_id == "legal-source-verify"
    assert verification.source_kind == "court_practice"
    assert verification.verification_status == "verified"
    assert verification.http_status == 200
    assert "full_text" not in (verification.verification_payload or {})
    source = db_session.get(LegalSource, "legal-source-verify")
    assert source is not None
    assert source.last_checked_at is not None


def test_controlled_official_source_search_plan_allows_only_triggered_search(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)

    response = client.post(
        "/n8n/official-source-search/plan",
        json={
            "workspace_id": "workspace-1",
            "user_id": "user-1",
            "query": "стаття 625 ЦК України",
            "trigger_reason": "low_rag_confidence",
            "rag_confidence": 0.2,
            "candidate_urls": [
                "https://zakon.rada.gov.ua/laws/show/435-15",
                "https://legal-blog.test/commentary",
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["search_allowed"] is True
    assert payload["site_queries"]
    assert all(query.startswith("site:") for query in payload["site_queries"])
    assert payload["accepted_urls"][0]["domain"] == "zakon.rada.gov.ua"
    assert payload["rejected_urls"][0]["reason"] in {
        "blocked_source_hint",
        "domain_not_allowlisted",
    }
    run = db_session.query(OfficialSourceSearchRun).one()
    assert run.search_allowed is True
    assert run.accepted_urls[0]["url"] == "https://zakon.rada.gov.ua/laws/show/435-15"


def test_controlled_official_source_search_plan_blocks_untriggered_search(
    client: TestClient,
    db_session: Session,
) -> None:
    _seed_workspace(db_session)

    response = client.post(
        "/n8n/official-source-search/plan",
        json={
            "workspace_id": "workspace-1",
            "user_id": "user-1",
            "query": "загальний пошук",
            "trigger_reason": "manual_review",
            "rag_confidence": 0.9,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["search_allowed"] is False
    assert payload["site_queries"] == []
    assert db_session.query(OfficialSourceSearchRun).one().search_allowed is False
