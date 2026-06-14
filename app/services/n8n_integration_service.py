from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.lawyer_profile import LawyerProfile
from app.models.n8n_intake import N8nIntakeItem, N8nIntakePackage, N8nTelegramBinding
from app.repositories.document_repository import DocumentRepository
from app.schemas.n8n_schema import (
    N8nIntakeResponse,
    N8nObsidianNoteRequest,
    N8nObsidianNoteResponse,
    N8nProcessPackageRequest,
    N8nProcessPackageResponse,
    N8nTelegramBindingRequest,
    N8nTelegramBindingResponse,
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
        event = self._event_with_resolved_identity(event)
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

        profile_response = self._handle_profile_onboarding(event)
        if profile_response is not None:
            return profile_response

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

    def upsert_telegram_binding(
        self,
        request: N8nTelegramBindingRequest,
    ) -> N8nTelegramBindingResponse:
        self.access_control.require_permission(
            workspace_id=request.workspace_id,
            user_id=request.user_id,
            permission=WorkspacePermission.WRITE_DOCUMENTS,
        )
        binding = (
            self.db.query(N8nTelegramBinding)
            .filter(N8nTelegramBinding.telegram_user_id == request.telegram_user_id)
            .one_or_none()
        )
        if binding is None:
            binding = N8nTelegramBinding(telegram_user_id=request.telegram_user_id)
            self.db.add(binding)

        binding.telegram_chat_id = request.telegram_chat_id
        binding.username = request.username
        binding.workspace_id = request.workspace_id
        binding.user_id = request.user_id
        binding.is_active = request.is_active
        binding.metadata_json = request.metadata
        self.db.flush()

        self.audit_log_service.record(
            AuditLogCommand(
                action="n8n.telegram_binding_upserted",
                user_id=request.user_id,
                workspace_id=request.workspace_id,
                object_type="n8n_telegram_binding",
                object_id=binding.id,
                metadata={
                    "telegram_user_id": request.telegram_user_id,
                    "telegram_chat_id": request.telegram_chat_id,
                    "is_active": request.is_active,
                },
            ),
            commit=False,
        )
        self.db.commit()
        self.db.refresh(binding)
        return N8nTelegramBindingResponse.model_validate(binding)

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
        metadata = dict(package.metadata_json or {})
        if request.client_profile_id:
            metadata["client_profile_id"] = request.client_profile_id
        package.metadata_json = metadata
        self.audit_log_service.record(
            AuditLogCommand(
                action="n8n.package_processing_requested",
                user_id=user_id,
                workspace_id=workspace_id,
                object_type="n8n_intake_package",
                object_id=package.id,
                metadata={
                    "requested_agent": request.requested_agent,
                    "client_profile_id": request.client_profile_id,
                },
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

    def _handle_profile_onboarding(self, event: TelegramIntakeEvent) -> N8nIntakeResponse | None:
        binding = self._get_active_binding(event.telegram_user_id)
        profile = (
            self.db.query(LawyerProfile).filter(LawyerProfile.user_id == event.user_id).one_or_none()
        )
        metadata = dict(binding.metadata_json or {}) if binding is not None else {}
        onboarding_state = metadata.get("onboarding_state")

        if event.action in {"edit_profile_prompt", "edit_lawyer_profile"}:
            if binding is not None:
                metadata["onboarding_state"] = "awaiting_system_prompt"
                binding.metadata_json = metadata
                self.db.commit()
            return N8nIntakeResponse(
                ok=True,
                reply_text=(
                    "Надішліть новий системний промпт: хто ви, ваша спеціалізація, "
                    "де і з чим працюєте, чиї інтереси відстоюєте та як має відповідати асистент."
                ),
            )

        if onboarding_state == "awaiting_system_prompt" and event.action == "free_text" and event.text:
            profile = self._upsert_lawyer_profile_from_text(
                user_id=event.user_id,
                text=event.text,
                mode="system_prompt",
                existing_profile=profile,
            )
            if binding is not None:
                metadata.pop("onboarding_state", None)
                binding.metadata_json = metadata
            self._record_profile_update(event, profile.id, "system_prompt")
            self.db.commit()
            return N8nIntakeResponse(
                ok=True,
                reply_text="Системний промпт оновлено. Тепер можете додавати матеріали або почати обробку.",
            )

        if profile is None:
            if onboarding_state == "awaiting_activity_direction" and event.action == "free_text" and event.text:
                profile = self._upsert_lawyer_profile_from_text(
                    user_id=event.user_id,
                    text=event.text,
                    mode="activity_direction",
                    existing_profile=None,
                )
                if binding is not None:
                    metadata.pop("onboarding_state", None)
                    binding.metadata_json = metadata
                self._record_profile_update(event, profile.id, "activity_direction")
                self.db.commit()
                return N8nIntakeResponse(
                    ok=True,
                    reply_text=(
                        "Профіль створено. Ви зможете змінити системний промпт у будь-який момент "
                        "через кнопку 'Змінити системний промпт'."
                    ),
                )

            if binding is not None:
                metadata["onboarding_state"] = "awaiting_activity_direction"
                binding.metadata_json = metadata
                self.db.commit()
            return N8nIntakeResponse(
                ok=True,
                reply_text=(
                    "Який напрямок Вашої діяльності? Опишіть вашу спеціалізацію, "
                    "де і з чим працюєте, чиї інтереси відстоюєте та бажаний стиль відповідей."
                ),
            )

        return None

    def _upsert_lawyer_profile_from_text(
        self,
        user_id: str,
        text: str,
        mode: str,
        existing_profile: LawyerProfile | None,
    ) -> LawyerProfile:
        clean_text = text.strip()
        if mode == "activity_direction":
            system_prompt = (
                "Ти юридичний AI-асистент, який працює відповідно до персонального профілю юриста. "
                f"Профіль юриста: {clean_text}. "
                "Відповідай практично, структуровано, українською мовою, з обережними висновками "
                "та нагадуванням перевіряти актуальні норми й судову практику."
            )
            values = {
                "system_prompt": system_prompt,
                "specialization": clean_text,
                "extra_context": {"activity_direction": clean_text},
            }
        else:
            values = {"system_prompt": clean_text}

        profile = existing_profile or LawyerProfile(user_id=user_id, system_prompt=values["system_prompt"])
        for field_name, value in values.items():
            setattr(profile, field_name, value)
        if existing_profile is None:
            self.db.add(profile)
        self.db.flush()
        return profile

    def _record_profile_update(
        self,
        event: TelegramIntakeEvent,
        profile_id: str,
        update_type: str,
    ) -> None:
        self.audit_log_service.record(
            AuditLogCommand(
                action="n8n.telegram_lawyer_profile_updated",
                user_id=event.user_id,
                workspace_id=event.workspace_id,
                object_type="lawyer_profile",
                object_id=profile_id,
                metadata={"update_type": update_type, "chat_id": event.chat_id},
            ),
            commit=False,
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

    def _event_with_resolved_identity(self, event: TelegramIntakeEvent) -> TelegramIntakeEvent:
        if event.workspace_id and event.user_id:
            return event
        if not event.telegram_user_id:
            return event

        binding = self._get_active_binding(event.telegram_user_id)
        if binding is None:
            return event

        updates = {
            "workspace_id": event.workspace_id or binding.workspace_id,
            "user_id": event.user_id or binding.user_id,
        }
        return event.model_copy(update=updates)

    def _get_active_binding(self, telegram_user_id: str | None) -> N8nTelegramBinding | None:
        if not telegram_user_id:
            return None
        return (
            self.db.query(N8nTelegramBinding)
            .filter(
                N8nTelegramBinding.telegram_user_id == telegram_user_id,
                N8nTelegramBinding.is_active.is_(True),
            )
            .one_or_none()
        )

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
