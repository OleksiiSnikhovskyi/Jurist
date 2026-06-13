import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.document import Document
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.access_control import AccessDeniedError, WorkspacePermission
from app.services.document_access_service import DocumentAccessService, DocumentNotFoundError


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    User.__table__.create(engine)
    Workspace.__table__.create(engine)
    WorkspaceMember.__table__.create(engine)
    Document.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _seed_access_case(db: Session) -> None:
    db.add(User(id="user-1", email="user@example.com", role="lawyer"))
    db.add(Workspace(id="workspace-a", name="Workspace A", owner_id="user-1", workspace_type="case"))
    db.add(Workspace(id="workspace-b", name="Workspace B", owner_id="user-1", workspace_type="case"))
    db.add(
        WorkspaceMember(
            id="member-1",
            workspace_id="workspace-a",
            user_id="user-1",
            role="lawyer",
        )
    )
    db.add(
        Document(
            id="document-a",
            workspace_id="workspace-a",
            uploaded_by="user-1",
            document_name="allowed.pdf",
        )
    )
    db.add(
        Document(
            id="document-b",
            workspace_id="workspace-b",
            uploaded_by="user-1",
            document_name="denied.pdf",
        )
    )
    db.commit()


def test_allows_document_access_inside_user_workspace(db_session: Session) -> None:
    _seed_access_case(db_session)

    document = DocumentAccessService(db_session).require_document_access(
        document_id="document-a",
        workspace_id="workspace-a",
        user_id="user-1",
        permission=WorkspacePermission.READ,
    )

    assert document.document_name == "allowed.pdf"


def test_denies_cross_workspace_document_access(db_session: Session) -> None:
    _seed_access_case(db_session)

    with pytest.raises(AccessDeniedError, match="Document does not belong"):
        DocumentAccessService(db_session).require_document_access(
            document_id="document-b",
            workspace_id="workspace-a",
            user_id="user-1",
            permission=WorkspacePermission.READ,
        )


def test_denies_when_user_is_not_workspace_member(db_session: Session) -> None:
    _seed_access_case(db_session)

    with pytest.raises(AccessDeniedError, match="not a member"):
        DocumentAccessService(db_session).require_document_access(
            document_id="document-a",
            workspace_id="workspace-a",
            user_id="missing-user",
            permission=WorkspacePermission.READ,
        )


def test_missing_document_returns_not_found(db_session: Session) -> None:
    _seed_access_case(db_session)

    with pytest.raises(DocumentNotFoundError):
        DocumentAccessService(db_session).require_document_access(
            document_id="missing-document",
            workspace_id="workspace-a",
            user_id="user-1",
            permission=WorkspacePermission.READ,
        )
