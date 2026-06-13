from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from app.models.workspace import WorkspaceMember
from app.repositories.workspace_repository import WorkspaceRepository


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    LAWYER = "lawyer"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class WorkspacePermission(StrEnum):
    READ = "read"
    WRITE_DOCUMENTS = "write_documents"
    REVIEW_DOCUMENTS = "review_documents"
    RUN_AGENTS = "run_agents"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_WORKSPACE = "manage_workspace"


ROLE_PERMISSIONS: dict[WorkspaceRole, frozenset[WorkspacePermission]] = {
    WorkspaceRole.OWNER: frozenset(WorkspacePermission),
    WorkspaceRole.ADMIN: frozenset(
        {
            WorkspacePermission.READ,
            WorkspacePermission.WRITE_DOCUMENTS,
            WorkspacePermission.REVIEW_DOCUMENTS,
            WorkspacePermission.RUN_AGENTS,
            WorkspacePermission.MANAGE_MEMBERS,
            WorkspacePermission.MANAGE_WORKSPACE,
        }
    ),
    WorkspaceRole.LAWYER: frozenset(
        {
            WorkspacePermission.READ,
            WorkspacePermission.WRITE_DOCUMENTS,
            WorkspacePermission.REVIEW_DOCUMENTS,
            WorkspacePermission.RUN_AGENTS,
        }
    ),
    WorkspaceRole.REVIEWER: frozenset(
        {
            WorkspacePermission.READ,
            WorkspacePermission.REVIEW_DOCUMENTS,
        }
    ),
    WorkspaceRole.VIEWER: frozenset({WorkspacePermission.READ}),
}


VALID_WORKSPACE_ROLES = frozenset(role.value for role in WorkspaceRole)


class AccessControlError(Exception):
    pass


class AccessDeniedError(AccessControlError):
    pass


class InvalidWorkspaceRoleError(AccessControlError):
    pass


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    role: WorkspaceRole | None
    permission: WorkspacePermission


def parse_workspace_role(role: str) -> WorkspaceRole:
    try:
        return WorkspaceRole(role)
    except ValueError as exc:
        raise InvalidWorkspaceRoleError(f"Unsupported workspace role: {role}") from exc


class AccessControlService:
    def __init__(self, db: Session, repository: WorkspaceRepository | None = None) -> None:
        self.repository = repository or WorkspaceRepository(db)

    def decide(
        self,
        workspace_id: str,
        user_id: str,
        permission: WorkspacePermission,
    ) -> AccessDecision:
        membership = self.repository.get_member(workspace_id, user_id)
        if membership is None:
            return AccessDecision(allowed=False, role=None, permission=permission)

        role = parse_workspace_role(membership.role)
        return AccessDecision(
            allowed=permission in ROLE_PERMISSIONS[role],
            role=role,
            permission=permission,
        )

    def require_permission(
        self,
        workspace_id: str,
        user_id: str,
        permission: WorkspacePermission,
    ) -> WorkspaceMember:
        membership = self.repository.get_member(workspace_id, user_id)
        if membership is None:
            raise AccessDeniedError("User is not a member of this workspace")

        role = parse_workspace_role(membership.role)
        if permission not in ROLE_PERMISSIONS[role]:
            raise AccessDeniedError("Workspace role does not allow this action")
        return membership
