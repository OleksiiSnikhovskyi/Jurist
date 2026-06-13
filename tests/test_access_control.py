import pytest

from app.models.workspace import WorkspaceMember
from app.services.access_control import (
    AccessControlService,
    AccessDeniedError,
    InvalidWorkspaceRoleError,
    WorkspacePermission,
    WorkspaceRole,
    parse_workspace_role,
)


class _MembershipRepository:
    def __init__(self, membership: WorkspaceMember | None) -> None:
        self.membership = membership

    def get_member(self, workspace_id: str, user_id: str) -> WorkspaceMember | None:
        if workspace_id == "workspace-1" and user_id == "user-1":
            return self.membership
        return None


def _service_for_role(role: str | None) -> AccessControlService:
    membership = None
    if role is not None:
        membership = WorkspaceMember(
            id="membership-1",
            workspace_id="workspace-1",
            user_id="user-1",
            role=role,
        )
    return AccessControlService(db=None, repository=_MembershipRepository(membership))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("role", "permission"),
    [
        (WorkspaceRole.OWNER, WorkspacePermission.MANAGE_WORKSPACE),
        (WorkspaceRole.ADMIN, WorkspacePermission.MANAGE_MEMBERS),
        (WorkspaceRole.LAWYER, WorkspacePermission.RUN_AGENTS),
        (WorkspaceRole.REVIEWER, WorkspacePermission.REVIEW_DOCUMENTS),
        (WorkspaceRole.VIEWER, WorkspacePermission.READ),
    ],
)
def test_roles_allow_expected_permissions(
    role: WorkspaceRole,
    permission: WorkspacePermission,
) -> None:
    membership = _service_for_role(role.value).require_permission(
        "workspace-1",
        "user-1",
        permission,
    )

    assert membership.role == role.value


@pytest.mark.parametrize(
    ("role", "permission"),
    [
        (WorkspaceRole.VIEWER, WorkspacePermission.WRITE_DOCUMENTS),
        (WorkspaceRole.REVIEWER, WorkspacePermission.MANAGE_MEMBERS),
        (WorkspaceRole.LAWYER, WorkspacePermission.MANAGE_WORKSPACE),
    ],
)
def test_roles_deny_forbidden_permissions(
    role: WorkspaceRole,
    permission: WorkspacePermission,
) -> None:
    with pytest.raises(AccessDeniedError):
        _service_for_role(role.value).require_permission("workspace-1", "user-1", permission)


def test_non_member_is_denied() -> None:
    decision = _service_for_role(None).decide(
        "workspace-1",
        "user-1",
        WorkspacePermission.READ,
    )

    assert decision.allowed is False
    assert decision.role is None


def test_unknown_role_is_rejected() -> None:
    with pytest.raises(InvalidWorkspaceRoleError):
        parse_workspace_role("guest")
