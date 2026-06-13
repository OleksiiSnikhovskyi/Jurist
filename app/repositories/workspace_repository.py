from sqlalchemy.orm import Session

from app.models.workspace import Workspace, WorkspaceMember


class WorkspaceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        return self.db.get(Workspace, workspace_id)

    def create_workspace(self, name: str, owner_id: str, workspace_type: str) -> Workspace:
        workspace = Workspace(name=name, owner_id=owner_id, workspace_type=workspace_type)
        self.db.add(workspace)
        self.db.flush()
        return workspace

    def get_member(self, workspace_id: str, user_id: str) -> WorkspaceMember | None:
        return (
            self.db.query(WorkspaceMember)
            .filter(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
            .one_or_none()
        )

    def add_member(self, workspace_id: str, user_id: str, role: str) -> WorkspaceMember:
        member = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
        self.db.add(member)
        self.db.flush()
        return member

    def list_workspaces_for_user(self, user_id: str) -> list[Workspace]:
        return (
            self.db.query(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .filter(WorkspaceMember.user_id == user_id)
            .order_by(Workspace.created_at.desc())
            .all()
        )
