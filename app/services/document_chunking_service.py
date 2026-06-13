from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.document import DocumentChunk
from app.repositories.document_repository import DocumentRepository
from app.services.access_control import WorkspacePermission
from app.services.audit_log_service import AuditLogCommand, AuditLogService
from app.services.chunking import split_text
from app.services.document_access_service import DocumentAccessService


class DocumentHasNoExtractedTextError(Exception):
    pass


@dataclass(frozen=True)
class DocumentChunkingCommand:
    document_id: str
    workspace_id: str
    user_id: str
    chunk_size: int = 1200
    overlap: int = 150


class DocumentChunkingService:
    def __init__(
        self,
        db: Session,
        document_repository: DocumentRepository | None = None,
        document_access_service: DocumentAccessService | None = None,
        audit_log_service: AuditLogService | None = None,
    ) -> None:
        self.db = db
        self.document_repository = document_repository or DocumentRepository(db)
        self.document_access_service = document_access_service or DocumentAccessService(
            db,
            document_repository=self.document_repository,
        )
        self.audit_log_service = audit_log_service or AuditLogService(db)

    def persist_chunks(self, command: DocumentChunkingCommand) -> list[DocumentChunk]:
        document = self.document_access_service.require_document_access(
            document_id=command.document_id,
            workspace_id=command.workspace_id,
            user_id=command.user_id,
            permission=WorkspacePermission.WRITE_DOCUMENTS,
        )
        if not document.extracted_text:
            raise DocumentHasNoExtractedTextError("Document has no extracted text")

        chunks = split_text(
            document.extracted_text,
            chunk_size=command.chunk_size,
            overlap=command.overlap,
        )
        self.document_repository.delete_chunks_for_document(document.id)
        persisted_chunks = self.document_repository.create_document_chunks(
            document_id=document.id,
            workspace_id=document.workspace_id,
            chunks=chunks,
        )
        self.audit_log_service.record(
            AuditLogCommand(
                action="document.chunked",
                user_id=command.user_id,
                workspace_id=command.workspace_id,
                object_type="document",
                object_id=document.id,
                metadata={"chunk_count": len(persisted_chunks)},
            ),
            commit=False,
        )
        self.db.commit()
        return persisted_chunks
