import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.services.workspace_service import (
    OWNER_ROLE,
    WorkspaceCreateCommand,
    WorkspaceInvalidRoleError,
    WorkspaceMemberAlreadyExistsError,
    WorkspaceMemberCommand,
    WorkspaceService,
    WorkspaceUserNotFoundError,
)


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    User.__table__.create(engine)
    Workspace.__table__.create(engine)
    WorkspaceMember.__table__.create(engine)
    SessionLocal = sessionmaker(bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _add_user(db: Session, user_id: str, email: str) -> User:
    user = User(id=user_id, email=email, role="lawyer")
    db.add(user)
    db.commit()
    return user


def test_create_workspace_adds_owner_membership(db_session: Session) -> None:
    _add_user(db_session, "owner-1", "owner@example.com")

    workspace = WorkspaceService(db_session).create_workspace(
        WorkspaceCreateCommand(name="Civil Cases", owner_id="owner-1")
    )

    membership = WorkspaceService(db_session).get_membership(workspace.id, "owner-1")
    assert workspace.name == "Civil Cases"
    assert workspace.owner_id == "owner-1"
    assert membership is not None
    assert membership.role == OWNER_ROLE


def test_create_workspace_requires_existing_owner(db_session: Session) -> None:
    with pytest.raises(WorkspaceUserNotFoundError):
        WorkspaceService(db_session).create_workspace(
            WorkspaceCreateCommand(name="Civil Cases", owner_id="missing-user")
        )


def test_add_member_rejects_duplicate_membership(db_session: Session) -> None:
    _add_user(db_session, "owner-1", "owner@example.com")
    _add_user(db_session, "member-1", "member@example.com")
    service = WorkspaceService(db_session)
    workspace = service.create_workspace(WorkspaceCreateCommand(name="Civil Cases", owner_id="owner-1"))

    service.add_member(
        WorkspaceMemberCommand(workspace_id=workspace.id, user_id="member-1", role="reviewer")
    )

    with pytest.raises(WorkspaceMemberAlreadyExistsError):
        service.add_member(
            WorkspaceMemberCommand(workspace_id=workspace.id, user_id="member-1", role="reviewer")
        )


def test_add_member_rejects_unknown_role(db_session: Session) -> None:
    _add_user(db_session, "owner-1", "owner@example.com")
    _add_user(db_session, "member-1", "member@example.com")
    service = WorkspaceService(db_session)
    workspace = service.create_workspace(WorkspaceCreateCommand(name="Civil Cases", owner_id="owner-1"))

    with pytest.raises(WorkspaceInvalidRoleError):
        service.add_member(
            WorkspaceMemberCommand(workspace_id=workspace.id, user_id="member-1", role="guest")
        )


def test_list_workspaces_for_user_returns_memberships_only(db_session: Session) -> None:
    _add_user(db_session, "owner-1", "owner@example.com")
    _add_user(db_session, "member-1", "member@example.com")
    service = WorkspaceService(db_session)
    visible_workspace = service.create_workspace(
        WorkspaceCreateCommand(name="Visible", owner_id="owner-1")
    )
    service.create_workspace(WorkspaceCreateCommand(name="Owner Only", owner_id="owner-1"))
    service.add_member(
        WorkspaceMemberCommand(
            workspace_id=visible_workspace.id,
            user_id="member-1",
            role="reviewer",
        )
    )

    workspaces = service.list_workspaces_for_user("member-1")

    assert [workspace.name for workspace in workspaces] == ["Visible"]
