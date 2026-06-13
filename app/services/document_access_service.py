from sqlalchemy.orm import Session

from app.models.document import Document
from app.repositories.document_repository import DocumentRepository
from app.services.access_control import AccessControlService, AccessDeniedError, WorkspacePermission


class DocumentNotFoundError(Exception):
    pass


class DocumentAccessService:
    def __init__(
        self,
        db: Session,
        document_repository: DocumentRepository | None = None,
        access_control: AccessControlService | None = None,
    ) -> None:
        self.document_repository = document_repository or DocumentRepository(db)
        self.access_control = access_control or AccessControlService(db)

    def require_document_access(
        self,
        *,
        document_id: str,
        workspace_id: str,
        user_id: str,
        permission: WorkspacePermission = WorkspacePermission.READ,
    ) -> Document:
        document = self.document_repository.get_document(document_id)
        if document is None:
            raise DocumentNotFoundError("Document not found")
        if document.workspace_id != workspace_id:
            raise AccessDeniedError("Document does not belong to this workspace")

        self.access_control.require_permission(
            workspace_id=workspace_id,
            user_id=user_id,
            permission=permission,
        )
        return document
