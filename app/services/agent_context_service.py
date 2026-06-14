from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.client_profile import ClientProfile
from app.services.access_control import AccessControlService, AccessDeniedError, WorkspacePermission


class ClientProfileNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class ClientContext:
    profile_id: str
    text: str


class AgentContextService:
    def __init__(
        self,
        db: Session,
        access_control: AccessControlService | None = None,
    ) -> None:
        self.db = db
        self.access_control = access_control or AccessControlService(db)

    def load_client_context(
        self,
        *,
        client_profile_id: str | None,
        workspace_id: str,
        user_id: str,
    ) -> ClientContext | None:
        if not client_profile_id:
            return None

        profile = self.db.get(ClientProfile, client_profile_id)
        if profile is None:
            raise ClientProfileNotFoundError("Client profile not found")
        if profile.workspace_id != workspace_id:
            raise AccessDeniedError("Client profile does not belong to this workspace")

        self.access_control.require_permission(
            workspace_id=workspace_id,
            user_id=user_id,
            permission=WorkspacePermission.READ,
        )
        return ClientContext(profile_id=profile.id, text=format_client_context(profile))


def format_client_context(profile: ClientProfile) -> str:
    parts = [
        f"Клієнт: {profile.display_name}",
        f"Тип клієнта: {profile.client_type}" if profile.client_type else None,
        f"Роль у справі: {profile.matter_role}" if profile.matter_role else None,
        f"Інтереси клієнта: {profile.interests}" if profile.interests else None,
        f"Ставлення до ризику: {profile.risk_preferences}" if profile.risk_preferences else None,
        (
            f"Комунікаційні уподобання: {profile.communication_preferences}"
            if profile.communication_preferences
            else None
        ),
        f"Фактичний контекст: {profile.factual_context}" if profile.factual_context else None,
    ]
    return "\n".join(part for part in parts if part)
