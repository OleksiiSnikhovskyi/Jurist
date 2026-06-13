import shutil
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.types import new_uuid
from app.repositories.document_repository import DocumentRepository
from app.services.access_control import AccessControlService, WorkspacePermission
from app.services.audit_log_service import AuditLogCommand, AuditLogService


@dataclass(frozen=True)
class DocumentUploadCommand:
    workspace_id: str
    user_id: str
    document_type: str | None = None
    confidentiality_level: str = "private"


class DocumentUploadService:
    def __init__(
        self,
        db: Session,
        upload_dir: str | Path,
        document_repository: DocumentRepository | None = None,
        access_control: AccessControlService | None = None,
        audit_log_service: AuditLogService | None = None,
    ) -> None:
        self.db = db
        self.upload_dir = Path(upload_dir)
        self.document_repository = document_repository or DocumentRepository(db)
        self.access_control = access_control or AccessControlService(db)
        self.audit_log_service = audit_log_service or AuditLogService(db)

    def upload(self, command: DocumentUploadCommand, file: UploadFile) -> Document:
        self.access_control.require_permission(
            workspace_id=command.workspace_id,
            user_id=command.user_id,
            permission=WorkspacePermission.WRITE_DOCUMENTS,
        )

        stored_path = self._store_file(file)
        document = self.document_repository.create_document(
            workspace_id=command.workspace_id,
            uploaded_by=command.user_id,
            document_name=file.filename or stored_path.name,
            document_type=command.document_type or file.content_type,
            file_path=str(stored_path),
            confidentiality_level=command.confidentiality_level,
        )
        self.audit_log_service.record(
            AuditLogCommand(
                action="document.uploaded",
                user_id=command.user_id,
                workspace_id=command.workspace_id,
                object_type="document",
                object_id=document.id,
                metadata={
                    "document_name": document.document_name,
                    "document_type": document.document_type,
                    "confidentiality_level": document.confidentiality_level,
                },
            ),
            commit=False,
        )
        self.db.commit()
        self.db.refresh(document)
        return document

    def _store_file(self, file: UploadFile) -> Path:
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(file.filename or "").suffix
        stored_path = self.upload_dir / f"{new_uuid()}{suffix}"
        with stored_path.open("wb") as output:
            shutil.copyfileobj(file.file, output)
        return stored_path
