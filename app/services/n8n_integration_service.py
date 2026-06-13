from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.n8n_intake import N8nIntakeItem, N8nIntakePackage
from app.repositories.document_repository import DocumentRepository
from app.schemas.n8n_schema import (
    N8nIntakeResponse,
    N8nObsidianNoteRequest,
    N8nObsidianNoteResponse,
    N8nProcessPackageRequest,
    N8nProcessPackageResponse,
    TelegramIntakeEvent,
)
from app.services.access_control import AccessControlService, WorkspacePermission
from app.services.audit_log_service import AuditLogCommand, AuditLogService
from app.services.chunking import split_text


class IntakePackageNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class PackageItemCounts:
    total: int
    attachments: int
    text_messages: int


class N8nIntegrationService:
    def __init__(
        self,
        db: Session,
        access_control: AccessControlService | None = None,
        document_repository: DocumentRepository | None = None,
        audit_log_service: AuditLogService | None = None,
    ) -> None:
        self.db = db
        self.access_control = access_control or AccessControlService(db)
        self.document_repository = document_repository or DocumentRepository(db)
        self.audit_log_service = audit_log_service or AuditLogService(db)

    def handle_telegram_event(self, event: TelegramIntakeEvent) -> N8nIntakeResponse:
        if not event.workspace_id or not event.user_id:
            return N8nIntakeResponse(
                ok=False,
                reply_text="Потрібно прив'язати Telegram до workspace і користувача перед додаванням матеріалів.",
            )

        self.access_control.require_permission(
            workspace_id=event.workspace_id,
            user_id=event.user_id,
            permission=WorkspacePermission.WRITE_DOCUMENTS,
        )
        package = self._get_or_create_pending_package(event)

        if event.action == "clear_package":
            package.status = "cleared"
            reply_text = "Поточний пакет очищено. Можна додати нові матеріали."
        elif event.action == "list_materials":
            counts = self._count_items(package.id)
            reply_text = (
                f"У пакеті матеріалів: {counts.total}. "
                f"Файлів/медіа: {counts.attachments}, текстових повідомлень: {counts.text_messages}."
            )
        elif event.action == "start_processing":
            package.status = "queued"
            package.requested_agent = event.requested_agent or "orchestrator"
            package.question = event.question or event.text
            reply_text = "Пакет поставлено в чергу на обробку."
        else:
            added_count = self._append_event_items(package, event)
            reply_text = (
                f"Додано матеріалів: {added_count}. Натисніть 'Почати обробку', коли пакет буде повним."
                if added_count
                else "Команду отримано. Додайте фото, документ або голосове повідомлення."
            )

        self.audit_log_service.record(
            AuditLogCommand(
                action="n8n.telegram_intake",
                user_id=event.user_id,
                workspace_id=event.workspace_id,
                object_type="n8n_intake_package",
                object_id=package.id,
                metadata={
                    "action": event.action,
                    "status": package.status,
                    "attachment_count": len(event.attachments),
                    "chat_id": event.chat_id,
                },
            ),
            commit=False,
        )
        self.db.commit()
        self.db.refresh(package)
        counts = self._count_items(package.id)
        return N8nIntakeResponse(
            ok=True,
            package_id=package.id,
            status=package.status,
            item_count=counts.total,
            reply_text=reply_text,
        )

    def start_package_processing(
        self,
        request: N8nProcessPackageRequest,
    ) -> N8nProcessPackageResponse:
        package = self.db.get(N8nIntakePackage, request.package_id)
        if package is None:
            raise IntakePackageNotFoundError("Intake package not found")

        workspace_id = request.workspace_id or package.workspace_id
        user_id = request.user_id or package.user_id
        if not workspace_id or not user_id:
            package.status = "needs_identity"
            self.db.commit()
            return N8nProcessPackageResponse(
                ok=False,
                package_id=package.id,
                status=package.status,
                item_count=self._count_items(package.id).total,
                message="Package has no workspace/user binding.",
            )

        self.access_control.require_permission(
            workspace_id=workspace_id,
            user_id=user_id,
            permission=WorkspacePermission.RUN_AGENTS,
        )
        package.workspace_id = workspace_id
        package.user_id = user_id
        package.status = "processing_requested"
        package.requested_agent = request.requested_agent
        package.question = request.question
        self.audit_log_service.record(
            AuditLogCommand(
                action="n8n.package_processing_requested",
                user_id=user_id,
                workspace_id=workspace_id,
                object_type="n8n_intake_package",
                object_id=package.id,
                metadata={"requested_agent": request.requested_agent},
            ),
            commit=False,
        )
        self.db.commit()
        return N8nProcessPackageResponse(
            ok=True,
            package_id=package.id,
            status=package.status,
            item_count=self._count_items(package.id).total,
            message="Package processing was requested.",
        )

    def sync_obsidian_note(self, request: N8nObsidianNoteRequest) -> N8nObsidianNoteResponse:
        self.access_control.require_permission(
            workspace_id=request.workspace_id,
            user_id=request.user_id,
            permission=WorkspacePermission.WRITE_DOCUMENTS,
        )
        document = self.document_repository.create_document(
            workspace_id=request.workspace_id,
            uploaded_by=request.user_id,
            document_name=request.note_path,
            document_type="obsidian_markdown",
            file_path=f"obsidian://{request.note_path}",
            confidentiality_level="private",
            extracted_text=request.markdown,
        )
        chunks = split_text(request.markdown, chunk_size=1200, overlap=150)
        persisted_chunks = self.document_repository.create_document_chunks(
            document_id=document.id,
            workspace_id=request.workspace_id,
            chunks=chunks,
        )
        self.audit_log_service.record(
            AuditLogCommand(
                action="n8n.obsidian_note_synced",
                user_id=request.user_id,
                workspace_id=request.workspace_id,
                object_type="document",
                object_id=document.id,
                metadata={
                    "note_path": request.note_path,
                    "sync_mode": request.sync_mode,
                    "tag_count": len(request.tags),
                    "link_count": len(request.links),
                    "chunk_count": len(persisted_chunks),
                },
            ),
            commit=False,
        )
        self.db.commit()
        self.db.refresh(document)
        return N8nObsidianNoteResponse(
            ok=True,
            document_id=document.id,
            chunk_count=len(persisted_chunks),
            message="Obsidian note synced.",
        )

    def _get_or_create_pending_package(self, event: TelegramIntakeEvent) -> N8nIntakePackage:
        package = (
            self.db.query(N8nIntakePackage)
            .filter(
                N8nIntakePackage.channel == "telegram",
                N8nIntakePackage.external_chat_id == event.chat_id,
                N8nIntakePackage.status == "pending",
            )
            .order_by(N8nIntakePackage.created_at.desc())
            .first()
        )
        if package is not None:
            package.workspace_id = package.workspace_id or event.workspace_id
            package.user_id = package.user_id or event.user_id
            return package

        package = N8nIntakePackage(
            workspace_id=event.workspace_id,
            user_id=event.user_id,
            channel="telegram",
            external_chat_id=event.chat_id,
            external_user_id=event.telegram_user_id,
            status="pending",
            metadata_json={"username": event.username},
        )
        self.db.add(package)
        self.db.flush()
        return package

    def _append_event_items(self, package: N8nIntakePackage, event: TelegramIntakeEvent) -> int:
        added_count = 0
        if event.text and event.action == "free_text":
            self.db.add(
                N8nIntakeItem(
                    package_id=package.id,
                    item_type="text",
                    text=event.text,
                    metadata_json={"message_id": event.message_id},
                )
            )
            added_count += 1

        for attachment in event.attachments:
            self.db.add(
                N8nIntakeItem(
                    package_id=package.id,
                    item_type=attachment.type,
                    external_file_id=attachment.file_id,
                    file_name=attachment.file_name,
                    mime_type=attachment.mime_type,
                    metadata_json={
                        "message_id": event.message_id,
                        "file_size": attachment.file_size,
                        "duration": attachment.duration,
                    },
                )
            )
            added_count += 1

        return added_count

    def _count_items(self, package_id: str) -> PackageItemCounts:
        items = self.db.query(N8nIntakeItem).filter(N8nIntakeItem.package_id == package_id).all()
        attachments = sum(1 for item in items if item.item_type != "text")
        text_messages = sum(1 for item in items if item.item_type == "text")
        return PackageItemCounts(
            total=len(items),
            attachments=attachments,
            text_messages=text_messages,
        )
