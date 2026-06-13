from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.access_control import VALID_WORKSPACE_ROLES


OWNER_ROLE = "owner"


class WorkspaceServiceError(Exception):
    pass


class WorkspaceNotFoundError(WorkspaceServiceError):
    pass


class WorkspaceUserNotFoundError(WorkspaceServiceError):
    pass


class WorkspaceMemberAlreadyExistsError(WorkspaceServiceError):
    pass


class WorkspaceInvalidRoleError(WorkspaceServiceError):
    pass


@dataclass(frozen=True)
class WorkspaceCreateCommand:
    name: str
    owner_id: str
    workspace_type: str = "legal_practice"


@dataclass(frozen=True)
class WorkspaceMemberCommand:
    workspace_id: str
    user_id: str
    role: str


class WorkspaceService:
    def __init__(self, db: Session, repository: WorkspaceRepository | None = None) -> None:
        self.db = db
        self.repository = repository or WorkspaceRepository(db)

    def create_workspace(self, command: WorkspaceCreateCommand) -> Workspace:
        self._ensure_user_exists(command.owner_id)
        workspace = self.repository.create_workspace(
            name=command.name,
            owner_id=command.owner_id,
            workspace_type=command.workspace_type,
        )
        self.repository.add_member(
            workspace_id=workspace.id,
            user_id=command.owner_id,
            role=OWNER_ROLE,
        )
        self.db.commit()
        self.db.refresh(workspace)
        return workspace

    def add_member(self, command: WorkspaceMemberCommand) -> WorkspaceMember:
        self._ensure_user_exists(command.user_id)
        self._ensure_valid_role(command.role)
        if self.repository.get_workspace(command.workspace_id) is None:
            raise WorkspaceNotFoundError("Workspace not found")
        if self.repository.get_member(command.workspace_id, command.user_id) is not None:
            raise WorkspaceMemberAlreadyExistsError("Workspace member already exists")

        member = self.repository.add_member(
            workspace_id=command.workspace_id,
            user_id=command.user_id,
            role=command.role,
        )
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise WorkspaceMemberAlreadyExistsError("Workspace member already exists") from exc
        self.db.refresh(member)
        return member

    def get_membership(self, workspace_id: str, user_id: str) -> WorkspaceMember | None:
        return self.repository.get_member(workspace_id, user_id)

    def list_workspaces_for_user(self, user_id: str) -> list[Workspace]:
        return self.repository.list_workspaces_for_user(user_id)

    def _ensure_user_exists(self, user_id: str) -> None:
        if self.db.get(User, user_id) is None:
            raise WorkspaceUserNotFoundError("User not found")

    def _ensure_valid_role(self, role: str) -> None:
        if role not in VALID_WORKSPACE_ROLES:
            raise WorkspaceInvalidRoleError(f"Unsupported workspace role: {role}")
