import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.client_profile import ClientProfile
from app.models.document import Document
from app.models.lawyer_profile import LawyerProfile
from app.models.legal_source import LegalSource
from app.models.n8n_intake import N8nIntakeItem, N8nIntakePackage, N8nTelegramBinding
from app.repositories.document_repository import DocumentRepository
from app.schemas.n8n_schema import (
    N8nExtractedTextRequest,
    N8nExtractedTextResponse,
    N8nIntakeResponse,
    N8nLegalSourceUpsertRequest,
    N8nLegalSourceUpsertResponse,
    N8nObsidianNoteRequest,
    N8nObsidianNoteResponse,
    N8nProcessPackageRequest,
    N8nProcessPackageResponse,
    N8nTelegramBindingRequest,
    N8nTelegramBindingResponse,
    TelegramIntakeEvent,
)
from app.services.access_control import AccessControlService, WorkspacePermission
from app.services.agent_context_service import AgentContextService
from app.services.audit_log_service import AuditLogCommand, AuditLogService
from app.services.chunking import split_text
from app.services.ollama_service import (
    LegalPackageAnalysisCommand,
    OllamaLegalAnalysisService,
    OllamaRequestError,
    SourceFragment,
)
from app.services.vector_search_service import VectorSearchCommand, VectorSearchService


class IntakePackageNotFoundError(Exception):
    pass


class LegalSourceValidationError(Exception):
    pass


class IntakeItemNotFoundError(Exception):
    pass


PUBLIC_SECTOR_KEYWORDS = (
    "комунальн",
    "закупів",
    "prozorro",
    "прозорро",
    "бюджетні кошти",
    "бюджетних коштів",
    "розпорядник бюджет",
    "казенн",
    "орган державної влади",
    "орган місцевого самоврядування",
    "державний замовник",
    "державного замовника",
    "державне підприємство",
    "державного підприємства",
    "державне майно",
    "державної власності",
    "публічні закупівлі",
    "публічних закупівель",
)

FINANCIAL_LEASING_KEYWORDS = (
    "фінансовий лізинг",
    "фінансового лізингу",
    "лізинг",
    "лізингодав",
    "лізингоодерж",
)

FOLLOWUP_REFERENCE_KEYWORDS = (
    "цей догов",
    "цього догов",
    "цьому догов",
    "цей документ",
    "цього документ",
    "цьому документ",
    "надісланий документ",
    "попередній документ",
    "по кожному",
    "за пунктами",
    "рекомендац",
    "удосконален",
)


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
        legal_analysis_service: OllamaLegalAnalysisService | None = None,
        vector_search_service: VectorSearchService | None = None,
        agent_context_service: AgentContextService | None = None,
    ) -> None:
        self.db = db
        self.access_control = access_control or AccessControlService(db)
        self.document_repository = document_repository or DocumentRepository(db)
        self.audit_log_service = audit_log_service or AuditLogService(db)
        self.legal_analysis_service = legal_analysis_service or OllamaLegalAnalysisService()
        self.vector_search_service = vector_search_service or VectorSearchService(db)
        self.agent_context_service = agent_context_service or AgentContextService(db)

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

        client_profile_response = self._handle_client_profile_onboarding(event)
        if client_profile_response is not None:
            return client_profile_response

        batch_menu_response = self._handle_batch_menu_navigation(event)
        if batch_menu_response is not None:
            return batch_menu_response

        batch_mode = self._telegram_intake_mode(event) == "batch"
        package = self._get_or_create_pending_package(event)
        reply_menu = "batch" if batch_mode else "main"

        if event.action == "clear_package":
            package.status = "cleared"
            reply_text = "Поточний пакет очищено. Можна додати нові матеріали."
            reply_menu = "batch"
        elif event.action == "list_materials":
            counts = self._count_items(package.id)
            reply_text = (
                f"У пакеті матеріалів: {counts.total}. "
                f"Файлів/медіа: {counts.attachments}, текстових повідомлень: {counts.text_messages}."
            )
            reply_menu = "batch"
        elif event.action == "start_processing":
            package.status = "queued"
            package.requested_agent = event.requested_agent or "orchestrator"
            package.question = event.question or event.text
            self._attach_active_client_profile(package, event)
            self._clear_incomplete_client_profile_draft(event)
            reply_text = self._try_process_package_with_llm(
                package=package,
                workspace_id=event.workspace_id,
                user_id=event.user_id,
            )
            reply_menu = "batch"
        else:
            added_count = self._append_event_items(package, event)
            if batch_mode:
                reply_text = (
                    f"Додано матеріалів: {added_count}. Натисніть 'Почати обробку', коли пакет буде повним."
                    if added_count
                    else "Команду отримано. Додайте фото, документ або голосове повідомлення до пакета."
                )
            elif added_count and event.attachments:
                package.status = "waiting_for_text_extraction"
                package.requested_agent = event.requested_agent or "orchestrator"
                package.question = event.question or event.text or "Проаналізуй надісланий документ."
                self._attach_active_client_profile(package, event)
                metadata = dict(package.metadata_json or {})
                metadata["auto_process_after_extraction"] = True
                package.metadata_json = metadata
                reply_text = (
                    "Документ або голосове повідомлення отримано. Після розпізнавання тексту "
                    "система автоматично запустить аналіз з активним профілем клієнта."
                )
            elif added_count:
                package.status = "queued"
                package.requested_agent = event.requested_agent or "orchestrator"
                package.question = event.question or event.text
                self._attach_active_client_profile(package, event)
                self._attach_recent_processed_context(package, event)
                reply_text = self._try_process_package_with_llm(
                    package=package,
                    workspace_id=event.workspace_id,
                    user_id=event.user_id,
                )
            else:
                reply_text = "Команду отримано. Для комплекту документів відкрийте 'Пакетна обробка'."

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
            reply_menu=reply_menu,
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
        elif "client_profile_id" not in metadata:
            active_client_profile_id = self._active_client_profile_id_for_package(package)
            if active_client_profile_id:
                metadata["client_profile_id"] = active_client_profile_id
        package.metadata_json = metadata
        answer = self._try_process_package_with_llm(
            package=package,
            workspace_id=workspace_id,
            user_id=user_id,
        )
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
            message=answer or "Package processing was requested.",
            answer=answer if package.status == "processed" else None,
        )

    def attach_extracted_text(
        self,
        request: N8nExtractedTextRequest,
    ) -> N8nExtractedTextResponse:
        package = self.db.get(N8nIntakePackage, request.package_id)
        if package is None:
            raise IntakePackageNotFoundError("Intake package not found")

        workspace_id = request.workspace_id or package.workspace_id
        user_id = request.user_id or package.user_id
        if not workspace_id or not user_id:
            raise IntakePackageNotFoundError("Package has no workspace/user binding")

        self.access_control.require_permission(
            workspace_id=workspace_id,
            user_id=user_id,
            permission=WorkspacePermission.WRITE_DOCUMENTS,
        )
        item = self._find_intake_item_for_extraction(request)
        if item is None or item.package_id != package.id:
            raise IntakeItemNotFoundError("Intake item not found for extracted text")

        clean_text = request.extracted_text.strip()
        item.text = clean_text
        item.file_name = request.file_name or item.file_name
        item.mime_type = request.mime_type or item.mime_type
        item.metadata_json = {
            **(item.metadata_json or {}),
            **request.metadata,
            "extraction_method": request.extraction_method,
            "extracted_at": datetime.now(UTC).isoformat(),
            "extracted_text_length": len(clean_text),
        }

        document = self._upsert_extracted_document(
            workspace_id=workspace_id,
            user_id=user_id,
            item=item,
            text=clean_text,
            document_type=request.document_type,
        )
        chunks = split_text(clean_text, chunk_size=request.chunk_size, overlap=request.overlap)
        self.document_repository.delete_chunks_for_document(document.id)
        persisted_chunks = self.document_repository.create_document_chunks(
            document_id=document.id,
            workspace_id=workspace_id,
            chunks=chunks,
        )

        package.status = "pending"
        package_metadata = {
            **(package.metadata_json or {}),
            "last_extracted_item_id": item.id,
            "last_extracted_document_id": document.id,
        }
        package.metadata_json = package_metadata
        if package_metadata.get("auto_process_after_extraction"):
            package_metadata.pop("auto_process_after_extraction", None)
            package_metadata["analysis_requested_after_extraction"] = True
            package_metadata["processing_note"] = (
                "Extracted text attached; analysis queued for explicit processing."
            )
            package.metadata_json = package_metadata
            package.status = "queued"
        self.audit_log_service.record(
            AuditLogCommand(
                action="n8n.intake_extracted_text_attached",
                user_id=user_id,
                workspace_id=workspace_id,
                object_type="n8n_intake_item",
                object_id=item.id,
                metadata={
                    "package_id": package.id,
                    "document_id": document.id,
                    "extraction_method": request.extraction_method,
                    "chunk_count": len(persisted_chunks),
                },
            ),
            commit=False,
        )
        self.db.commit()
        return N8nExtractedTextResponse(
            ok=True,
            package_id=package.id,
            item_id=item.id,
            document_id=document.id,
            chunk_count=len(persisted_chunks),
            message=(
                "Extracted text attached and queued for analysis."
                if package.status == "queued"
                else "Extracted text attached and indexed."
            ),
            status=package.status,
            answer=None,
        )

    def _try_process_package_with_llm(
        self,
        *,
        package: N8nIntakePackage,
        workspace_id: str,
        user_id: str,
    ) -> str:
        if not self.legal_analysis_service.is_configured():
            return "Пакет поставлено в чергу на обробку. LLM ще не налаштовано для FastAPI."

        command = self._build_package_analysis_command(
            package=package,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if not command.package_text.strip():
            package.status = "waiting_for_text_extraction"
            metadata = dict(package.metadata_json or {})
            metadata["processing_note"] = "No extracted text is available for LLM analysis."
            package.metadata_json = metadata
            return (
                "Пакет містить вкладення, але текст із файлів ще не витягнуто. "
                "Потрібно підключити завантаження файлів Telegram/OCR/парсинг документів перед LLM-аналізом."
            )

        try:
            result = self.legal_analysis_service.analyze_package(command)
        except OllamaRequestError as exc:
            package.status = "llm_error"
            metadata = dict(package.metadata_json or {})
            metadata["llm_error"] = str(exc)
            package.metadata_json = metadata
            return f"Пакет прийнято, але Ollama не змогла сформувати відповідь: {exc}"

        answer = self._sanitize_answer_for_package(
            answer=result.answer,
            package_text=command.package_text,
        )
        package.status = "processed"
        metadata = dict(package.metadata_json or {})
        metadata["llm_model"] = result.model
        metadata["llm_answer"] = answer
        metadata["processed_at"] = datetime.now(UTC).isoformat()
        package.metadata_json = metadata
        return answer

    def _build_package_analysis_command(
        self,
        *,
        package: N8nIntakePackage,
        workspace_id: str,
        user_id: str,
    ) -> LegalPackageAnalysisCommand:
        package_metadata = dict(package.metadata_json or {})
        source_package_id = package_metadata.get("followup_source_package_id")
        source_items: list[N8nIntakeItem] = []
        if source_package_id:
            source_items = (
                self.db.query(N8nIntakeItem)
                .filter(N8nIntakeItem.package_id == source_package_id)
                .order_by(N8nIntakeItem.created_at.asc())
                .all()
            )

        items = (
            self.db.query(N8nIntakeItem)
            .filter(N8nIntakeItem.package_id == package.id)
            .order_by(N8nIntakeItem.created_at.asc())
            .all()
        )
        source_text_parts = [
            f"- [попередній пакет: {item.item_type}] {item.text.strip()}"
            for item in source_items
            if item.text and item.text.strip()
        ]
        text_parts = [
            f"- [{item.item_type}] {item.text.strip()}"
            for item in items
            if item.text and item.text.strip()
        ]
        attachment_notes = [
            self._format_attachment_note(item)
            for item in items
            if item.item_type != "text"
        ]
        package_text = "\n".join(source_text_parts + text_parts)
        question = package.question or "Опрацюй матеріали пакета та підготуй юридичну відповідь."
        lawyer_profile = (
            self.db.query(LawyerProfile)
            .filter(LawyerProfile.user_id == user_id)
            .one_or_none()
        )
        lawyer_system_prompt = (
            lawyer_profile.system_prompt
            if lawyer_profile is not None
            else "Працюй як юридичний асистент українського юриста."
        )
        client_context = None
        client_profile_id = package_metadata.get("client_profile_id")
        if client_profile_id:
            client = self.agent_context_service.load_client_context(
                client_profile_id=client_profile_id,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            client_context = client.text if client else None

        source_fragments: list[SourceFragment] = []
        query_text = f"{question}\n{package_text}".strip()
        if query_text:
            results = self.vector_search_service.search(
                VectorSearchCommand(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    query=query_text,
                    limit=6,
                )
            )
            source_fragments = [
                SourceFragment(
                    document_id=result.document_id,
                    chunk_index=result.chunk_index,
                    score=result.score,
                    text=result.chunk_text[:900],
                )
                for result in results
            ]
            source_fragments = self._filter_source_fragments_for_package(
                package_text=package_text,
                fragments=source_fragments,
            )

        return LegalPackageAnalysisCommand(
            question=question,
            package_text=package_text,
            lawyer_system_prompt=lawyer_system_prompt,
            client_context=client_context,
            source_fragments=source_fragments,
            attachment_notes=attachment_notes,
        )

    def _filter_source_fragments_for_package(
        self,
        *,
        package_text: str,
        fragments: list[SourceFragment],
    ) -> list[SourceFragment]:
        package_lower = package_text.lower()
        has_public_sector_context = self._has_public_sector_context(package_lower)
        has_leasing_context = any(keyword in package_lower for keyword in FINANCIAL_LEASING_KEYWORDS)

        filtered: list[SourceFragment] = []
        for fragment in fragments:
            fragment_lower = fragment.text.lower()
            if (
                not has_public_sector_context
                and any(keyword in fragment_lower for keyword in PUBLIC_SECTOR_KEYWORDS)
            ):
                continue
            if (
                not has_leasing_context
                and any(keyword in fragment_lower for keyword in FINANCIAL_LEASING_KEYWORDS)
            ):
                continue
            filtered.append(fragment)
        return filtered

    def _sanitize_answer_for_package(self, *, answer: str, package_text: str) -> str:
        if self._has_public_sector_context(package_text.lower()):
            return answer

        forbidden_keywords = (
            "публічн",
            "закупів",
            "prozorro",
            "прозорро",
            "державний замовник",
            "державного замовника",
            "державне майно",
            "державної власності",
        )
        clean_lines: list[str] = []
        for line in answer.splitlines():
            if not any(keyword in line.lower() for keyword in forbidden_keywords):
                clean_lines.append(line)
                continue

            sentences = re.split(r"(?<=[.!?])\s+", line)
            kept = [
                sentence
                for sentence in sentences
                if sentence and not any(keyword in sentence.lower() for keyword in forbidden_keywords)
            ]
            if kept:
                clean_lines.append(" ".join(kept))
        return "\n".join(clean_lines).strip()

    def _has_public_sector_context(self, text_lower: str) -> bool:
        return any(keyword in text_lower for keyword in PUBLIC_SECTOR_KEYWORDS)

    def _attach_recent_processed_context(
        self,
        package: N8nIntakePackage,
        event: TelegramIntakeEvent,
    ) -> None:
        if event.action != "free_text" or event.attachments or not event.text:
            return
        text_lower = event.text.lower()
        if not any(keyword in text_lower for keyword in FOLLOWUP_REFERENCE_KEYWORDS):
            return

        recent_package = (
            self.db.query(N8nIntakePackage)
            .filter(
                N8nIntakePackage.channel == "telegram",
                N8nIntakePackage.external_chat_id == event.chat_id,
                N8nIntakePackage.status == "processed",
                N8nIntakePackage.id != package.id,
            )
            .order_by(N8nIntakePackage.updated_at.desc(), N8nIntakePackage.created_at.desc())
            .first()
        )
        if recent_package is None:
            return

        metadata = dict(package.metadata_json or {})
        metadata["followup_source_package_id"] = recent_package.id
        package.metadata_json = metadata

    def _find_intake_item_for_extraction(
        self,
        request: N8nExtractedTextRequest,
    ) -> N8nIntakeItem | None:
        if request.item_id:
            return self.db.get(N8nIntakeItem, request.item_id)
        query = self.db.query(N8nIntakeItem).filter(N8nIntakeItem.package_id == request.package_id)
        if request.external_file_id:
            query = query.filter(N8nIntakeItem.external_file_id == request.external_file_id)
        return query.order_by(N8nIntakeItem.created_at.desc()).first()

    def _upsert_extracted_document(
        self,
        *,
        workspace_id: str,
        user_id: str,
        item: N8nIntakeItem,
        text: str,
        document_type: str | None,
    ) -> Document:
        file_key = item.external_file_id or item.id
        file_path = f"telegram://{item.item_type}/{file_key}"
        document = (
            self.db.query(Document)
            .filter(
                Document.workspace_id == workspace_id,
                Document.file_path == file_path,
            )
            .one_or_none()
        )
        document_name = item.file_name or f"{item.item_type}-{item.id}"
        resolved_document_type = document_type or f"telegram_{item.item_type}"
        if document is None:
            return self.document_repository.create_document(
                workspace_id=workspace_id,
                uploaded_by=user_id,
                document_name=document_name[:500],
                document_type=resolved_document_type,
                file_path=file_path,
                confidentiality_level="private",
                extracted_text=text,
            )

        document.uploaded_by = user_id
        document.document_name = document_name[:500]
        document.document_type = resolved_document_type
        document.extracted_text = text
        self.db.add(document)
        self.db.flush()
        return document

    def _format_attachment_note(self, item: N8nIntakeItem) -> str:
        parts = [
            f"- type={item.item_type}",
            f"file_name={item.file_name}" if item.file_name else None,
            f"mime_type={item.mime_type}" if item.mime_type else None,
            f"file_id={item.external_file_id}" if item.external_file_id else None,
        ]
        return ", ".join(part for part in parts if part)

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

    def upsert_legal_source(
        self,
        request: N8nLegalSourceUpsertRequest,
    ) -> N8nLegalSourceUpsertResponse:
        self.access_control.require_permission(
            workspace_id=request.workspace_id,
            user_id=request.user_id,
            permission=WorkspacePermission.WRITE_DOCUMENTS,
        )
        if urlparse(request.source_url).hostname != "zakon.rada.gov.ua":
            raise LegalSourceValidationError("Only official zakon.rada.gov.ua sources are accepted here.")

        legal_source = (
            self.db.query(LegalSource).filter(LegalSource.source_url == request.source_url).one_or_none()
        )
        if legal_source is None:
            legal_source = LegalSource(
                source_type=request.source_type,
                source_name=request.source_name,
                source_url=request.source_url,
            )
            self.db.add(legal_source)
            self.db.flush()

        legal_source.source_type = request.source_type
        legal_source.source_name = request.source_name
        legal_source.source_url = request.source_url
        legal_source.jurisdiction = request.jurisdiction
        legal_source.document_number = request.document_number
        legal_source.adoption_date = self._parse_optional_date(request.adoption_date)
        legal_source.effective_date = self._parse_optional_date(request.effective_date)
        legal_source.validity_status = request.validity_status
        legal_source.last_checked_at = request.last_checked_at or datetime.now(UTC)
        legal_source.topic_tags = request.topic_tags
        legal_source.summary = request.summary
        legal_source.full_text = request.full_text

        file_path = request.file_path or f"rada://{request.source_url}"
        document = (
            self.db.query(Document)
            .filter(
                Document.workspace_id == request.workspace_id,
                Document.file_path == file_path,
            )
            .one_or_none()
        )
        if document is None:
            document = Document(
                workspace_id=request.workspace_id,
                uploaded_by=request.user_id,
                document_name=request.source_name,
                document_type=f"legal_source_{request.source_type}",
                file_path=file_path,
                extracted_text=request.full_text,
                confidentiality_level="public",
            )
            self.db.add(document)
            self.db.flush()
        else:
            document.uploaded_by = request.user_id
            document.document_name = request.source_name
            document.document_type = f"legal_source_{request.source_type}"
            document.extracted_text = request.full_text

        chunks = split_text(
            request.full_text,
            chunk_size=request.chunk_size,
            overlap=request.overlap,
        )
        self.document_repository.delete_chunks_for_document(document.id)
        persisted_chunks = self.document_repository.create_document_chunks(
            document_id=document.id,
            workspace_id=request.workspace_id,
            chunks=chunks,
        )
        self.audit_log_service.record(
            AuditLogCommand(
                action="n8n.legal_source_upserted",
                user_id=request.user_id,
                workspace_id=request.workspace_id,
                object_type="legal_source",
                object_id=legal_source.id,
                metadata={
                    "source_url": request.source_url,
                    "source_type": request.source_type,
                    "document_id": document.id,
                    "chunk_count": len(persisted_chunks),
                    "tag_count": len(request.topic_tags),
                },
            ),
            commit=False,
        )
        self.db.commit()
        return N8nLegalSourceUpsertResponse(
            ok=True,
            legal_source_id=legal_source.id,
            document_id=document.id,
            chunk_count=len(persisted_chunks),
            message="Legal source synced.",
        )

    def _parse_optional_date(self, value: str | None) -> date | None:
        if not value:
            return None
        for date_format in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(value, date_format).date()
            except ValueError:
                continue
        raise LegalSourceValidationError(f"Unsupported date format: {value}")

    def _handle_client_profile_onboarding(self, event: TelegramIntakeEvent) -> N8nIntakeResponse | None:
        binding = self._get_active_binding(event.telegram_user_id)
        if binding is None:
            return None

        metadata = dict(binding.metadata_json or {})
        onboarding_state = metadata.get("onboarding_state")
        draft = dict(metadata.get("client_profile_draft") or {})

        if event.action == "main_menu":
            is_client_onboarding = isinstance(
                onboarding_state,
                str,
            ) and (
                onboarding_state.startswith("awaiting_client_") or onboarding_state == "client_menu"
            )
            if is_client_onboarding:
                metadata.pop("onboarding_state", None)
                metadata.pop("client_profile_draft", None)
                metadata.pop("client_profile_edit_id", None)
                metadata.pop("client_profile_selection", None)
                binding.metadata_json = metadata
                self.db.commit()
            elif metadata.get("intake_mode") == "batch":
                metadata.pop("intake_mode", None)
                binding.metadata_json = metadata
                self.db.commit()
            return N8nIntakeResponse(
                ok=True,
                reply_text=(
                    "Головне меню. Можете додати матеріали, обрати клієнта "
                    "або почати обробку."
                ),
            )

        if event.action == "client_menu":
            profile = self._get_active_client_profile(metadata)
            metadata["onboarding_state"] = "client_menu"
            metadata.pop("client_profile_draft", None)
            metadata.pop("client_profile_edit_id", None)
            binding.metadata_json = metadata
            self.db.commit()
            active_text = (
                f"Активний клієнт: {profile.display_name}"
                if profile is not None
                else "Активний клієнт не обраний."
            )
            return N8nIntakeResponse(
                ok=True,
                reply_menu="client",
                reply_text=(
                    f"Підменю клієнтів.\n{active_text}\n\n"
                    "Оберіть дію кнопкою: створити, обрати, показати, змінити або видалити "
                    "профіль клієнта."
                ),
            )

        if event.action == "create_client_profile":
            metadata["onboarding_state"] = "awaiting_client_display_name"
            metadata["client_profile_draft"] = {}
            metadata.pop("client_profile_edit_id", None)
            binding.metadata_json = metadata
            self.db.commit()
            return N8nIntakeResponse(
                ok=True,
                reply_menu="client",
                reply_text="Введіть ім'я або назву клієнта.",
            )

        if event.action == "edit_client_profile":
            profile = self._get_active_client_profile(metadata)
            if profile is None:
                return N8nIntakeResponse(
                    ok=True,
                    reply_menu="client",
                    reply_text=(
                        "Активний клієнт не обраний. Спочатку натисніть 'Обрати клієнта' "
                        "або створіть новий профіль."
                    ),
                )
            metadata["onboarding_state"] = "awaiting_client_display_name"
            metadata["client_profile_draft"] = {}
            metadata["client_profile_edit_id"] = profile.id
            binding.metadata_json = metadata
            self.db.commit()
            return N8nIntakeResponse(
                ok=True,
                reply_menu="client",
                reply_text=(
                    f"Поточний профіль клієнта:\n{self._format_active_client_profile(profile)}\n\n"
                    "Надішліть нове ім'я або назву клієнта."
                ),
            )

        if event.action == "delete_client_profile":
            profiles = self._list_client_profiles(event.workspace_id)
            if not profiles:
                return N8nIntakeResponse(
                    ok=True,
                    reply_menu="client",
                    reply_text="Профілі клієнтів ще не створені. Немає що видаляти.",
                )
            metadata["onboarding_state"] = "awaiting_client_delete_selection"
            metadata["client_profile_selection"] = self._client_profile_selection(profiles)
            metadata.pop("client_profile_draft", None)
            metadata.pop("client_profile_edit_id", None)
            binding.metadata_json = metadata
            self.db.commit()
            names = self._format_numbered_client_profiles(profiles)
            return N8nIntakeResponse(
                ok=True,
                reply_menu="client",
                reply_text=(
                    "Надішліть номер клієнта, якого потрібно видалити:\n"
                    f"{names}\n\n"
                    "Щоб скасувати, натисніть 'Назад'."
                ),
            )

        if event.action == "select_client_profile":
            profiles = self._list_client_profiles(event.workspace_id)
            if not profiles:
                return N8nIntakeResponse(
                    ok=True,
                    reply_menu="client",
                    reply_text="Профілі клієнтів ще не створені. Натисніть 'Створити профіль клієнта'.",
                )
            metadata["onboarding_state"] = "awaiting_client_selection"
            metadata["client_profile_selection"] = self._client_profile_selection(profiles)
            binding.metadata_json = metadata
            self.db.commit()
            names = self._format_numbered_client_profiles(profiles)
            return N8nIntakeResponse(
                ok=True,
                reply_menu="client",
                reply_text=f"Надішліть номер клієнта зі списку:\n{names}",
            )

        if onboarding_state == "client_menu" and event.action == "free_text":
            return N8nIntakeResponse(
                ok=True,
                reply_menu="client",
                reply_text=(
                    "Ви у підменю клієнтів. Оберіть дію кнопкою: "
                    "'Створити профіль клієнта', 'Обрати клієнта', "
                    "'Змінити профіль клієнта' або 'Видалити клієнта'."
                ),
            )

        if (
            onboarding_state == "awaiting_client_delete_selection"
            and event.action == "free_text"
            and event.text
        ):
            profile = self._find_client_profile_by_selection(
                workspace_id=event.workspace_id,
                selection_text=event.text,
                metadata=metadata,
            )
            if profile is None:
                return N8nIntakeResponse(
                    ok=True,
                    reply_menu="client",
                    reply_text="Не знайшов такого номера. Надішліть номер зі списку або натисніть 'Назад'.",
                )
            active_client_profile_id = metadata.get("active_client_profile_id")
            if active_client_profile_id == profile.id:
                metadata.pop("active_client_profile_id", None)
            metadata.pop("onboarding_state", None)
            metadata.pop("client_profile_selection", None)
            binding.metadata_json = metadata
            self._record_client_profile_update(event, profile.id, "deleted")
            self.db.delete(profile)
            self.db.commit()
            return N8nIntakeResponse(
                ok=True,
                reply_menu="client",
                reply_text=f"Профіль клієнта '{profile.display_name}' видалено.",
            )

        if event.action == "show_active_client_profile":
            profile = self._get_active_client_profile(metadata)
            return N8nIntakeResponse(
                ok=True,
                reply_menu="client",
                reply_text=(
                    self._format_active_client_profile(profile)
                    if profile is not None
                    else "Активний клієнт не обраний. Створіть або оберіть профіль клієнта."
                ),
            )

        if onboarding_state == "awaiting_client_selection" and event.action == "free_text" and event.text:
            profile = self._find_client_profile_by_selection(
                workspace_id=event.workspace_id,
                selection_text=event.text,
                metadata=metadata,
            )
            if profile is None:
                return N8nIntakeResponse(
                    ok=True,
                    reply_menu="client",
                    reply_text="Не знайшов такого номера. Надішліть номер зі списку або створіть новий профіль.",
                )
            metadata["active_client_profile_id"] = profile.id
            metadata.pop("onboarding_state", None)
            metadata.pop("client_profile_selection", None)
            binding.metadata_json = metadata
            self.db.commit()
            return N8nIntakeResponse(
                ok=True,
                reply_menu="client",
                reply_text=f"Активний клієнт: {profile.display_name}. Його профіль буде додано до обробки запитів.",
            )

        if onboarding_state == "awaiting_client_display_name" and event.action == "free_text" and event.text:
            draft["display_name"] = event.text.strip()
            metadata["client_profile_draft"] = draft
            metadata["onboarding_state"] = "awaiting_client_matter_role"
            binding.metadata_json = metadata
            self.db.commit()
            return N8nIntakeResponse(
                ok=True,
                reply_menu="client",
                reply_text="Яка роль клієнта у справі?",
            )

        if onboarding_state == "awaiting_client_matter_role" and event.action == "free_text" and event.text:
            draft["matter_role"] = event.text.strip()
            metadata["client_profile_draft"] = draft
            metadata["onboarding_state"] = "awaiting_client_interests"
            binding.metadata_json = metadata
            self.db.commit()
            return N8nIntakeResponse(
                ok=True,
                reply_menu="client",
                reply_text="Які інтереси клієнта потрібно відстоювати?",
            )

        if onboarding_state == "awaiting_client_interests" and event.action == "free_text" and event.text:
            draft["interests"] = event.text.strip()
            metadata["client_profile_draft"] = draft
            metadata["onboarding_state"] = "awaiting_client_risk_preferences"
            binding.metadata_json = metadata
            self.db.commit()
            return N8nIntakeResponse(
                ok=True,
                reply_menu="client",
                reply_text="Які ризикові побажання клієнта? Наприклад: обережна позиція, швидке врегулювання, готовність до суду.",
            )

        if onboarding_state == "awaiting_client_risk_preferences" and event.action == "free_text" and event.text:
            draft["risk_preferences"] = event.text.strip()
            metadata["client_profile_draft"] = draft
            metadata["onboarding_state"] = "awaiting_client_communication_preferences"
            binding.metadata_json = metadata
            self.db.commit()
            return N8nIntakeResponse(
                ok=True,
                reply_menu="client",
                reply_text="Який стиль комунікації/відповіді бажаний для цього клієнта?",
            )

        if (
            onboarding_state == "awaiting_client_communication_preferences"
            and event.action == "free_text"
            and event.text
        ):
            draft["communication_preferences"] = event.text.strip()
            edit_profile_id = metadata.get("client_profile_edit_id")
            profile = (
                self._update_client_profile_from_draft(event, edit_profile_id, draft)
                if edit_profile_id
                else self._create_client_profile_from_draft(event, draft)
            )
            metadata["active_client_profile_id"] = profile.id
            metadata.pop("onboarding_state", None)
            metadata.pop("client_profile_draft", None)
            metadata.pop("client_profile_edit_id", None)
            binding.metadata_json = metadata
            self._record_client_profile_update(
                event,
                profile.id,
                "updated" if edit_profile_id else "created",
            )
            self.db.commit()
            action_text = (
                "оновлено і залишено активним"
                if edit_profile_id
                else "створено і зроблено активним"
            )
            return N8nIntakeResponse(
                ok=True,
                reply_menu="client",
                reply_text=(
                    f"Профіль клієнта '{profile.display_name}' {action_text}. "
                    "Його контекст буде додано до обробки запитів."
                ),
            )

        return None

    def _handle_batch_menu_navigation(self, event: TelegramIntakeEvent) -> N8nIntakeResponse | None:
        binding = self._get_active_binding(event.telegram_user_id)
        if binding is None:
            return None
        metadata = dict(binding.metadata_json or {})
        if event.action != "batch_processing_menu":
            return None

        metadata["intake_mode"] = "batch"
        metadata.pop("onboarding_state", None)
        metadata.pop("client_profile_draft", None)
        metadata.pop("client_profile_edit_id", None)
        metadata.pop("client_profile_selection", None)
        binding.metadata_json = metadata
        self.db.commit()
        return N8nIntakeResponse(
            ok=True,
            reply_menu="batch",
            reply_text=(
                "Пакетна обробка увімкнена. Додайте всі фото, документи або голосові повідомлення, "
                "а потім натисніть 'Почати обробку'."
            ),
        )

    def _telegram_intake_mode(self, event: TelegramIntakeEvent) -> str | None:
        binding = self._get_active_binding(event.telegram_user_id)
        if binding is None:
            return None
        metadata = dict(binding.metadata_json or {})
        return metadata.get("intake_mode")

    def _create_client_profile_from_draft(
        self,
        event: TelegramIntakeEvent,
        draft: dict,
    ) -> ClientProfile:
        profile = ClientProfile(
            workspace_id=event.workspace_id,
            created_by=event.user_id,
            display_name=draft.get("display_name") or "Клієнт",
            matter_role=draft.get("matter_role"),
            interests=draft.get("interests"),
            risk_preferences=draft.get("risk_preferences"),
            communication_preferences=draft.get("communication_preferences"),
            extra_context={"source": "telegram_onboarding"},
        )
        self.db.add(profile)
        self.db.flush()
        return profile

    def _update_client_profile_from_draft(
        self,
        event: TelegramIntakeEvent,
        profile_id: str,
        draft: dict,
    ) -> ClientProfile:
        profile = self.db.get(ClientProfile, profile_id)
        if profile is None or profile.workspace_id != event.workspace_id:
            return self._create_client_profile_from_draft(event, draft)
        profile.display_name = draft.get("display_name") or profile.display_name
        profile.matter_role = draft.get("matter_role")
        profile.interests = draft.get("interests")
        profile.risk_preferences = draft.get("risk_preferences")
        profile.communication_preferences = draft.get("communication_preferences")
        profile.extra_context = {
            **(profile.extra_context or {}),
            "source": "telegram_onboarding",
            "last_telegram_update": "profile_edit",
        }
        self.db.flush()
        return profile

    def _list_client_profiles(self, workspace_id: str | None) -> list[ClientProfile]:
        if not workspace_id:
            return []
        return (
            self.db.query(ClientProfile)
            .filter(ClientProfile.workspace_id == workspace_id)
            .order_by(ClientProfile.created_at.desc())
            .all()
        )

    def _client_profile_selection(self, profiles: list[ClientProfile]) -> list[dict[str, str]]:
        return [
            {"number": str(index), "id": profile.id, "display_name": profile.display_name}
            for index, profile in enumerate(profiles[:10], start=1)
        ]

    def _format_numbered_client_profiles(self, profiles: list[ClientProfile]) -> str:
        return "\n".join(
            f"{index}. {profile.display_name}"
            for index, profile in enumerate(profiles[:10], start=1)
        )

    def _find_client_profile_by_selection(
        self,
        *,
        workspace_id: str | None,
        selection_text: str,
        metadata: dict,
    ) -> ClientProfile | None:
        clean_selection = selection_text.strip()
        selected_id = None
        if clean_selection.isdecimal():
            for item in metadata.get("client_profile_selection") or []:
                if str(item.get("number")) == clean_selection:
                    selected_id = item.get("id")
                    break
            if selected_id is None:
                profiles = self._list_client_profiles(workspace_id)
                index = int(clean_selection) - 1
                if 0 <= index < min(len(profiles), 10):
                    selected_id = profiles[index].id
            if selected_id:
                profile = self.db.get(ClientProfile, selected_id)
                if profile is not None and profile.workspace_id == workspace_id:
                    return profile
                return None
        return self._find_client_profile_by_name(workspace_id, selection_text)

    def _find_client_profile_by_name(
        self,
        workspace_id: str | None,
        display_name: str,
    ) -> ClientProfile | None:
        clean_name = display_name.strip().lower()
        for profile in self._list_client_profiles(workspace_id):
            if profile.display_name.lower() == clean_name:
                return profile
        return None

    def _get_active_client_profile(self, metadata: dict) -> ClientProfile | None:
        active_client_profile_id = metadata.get("active_client_profile_id")
        if not active_client_profile_id:
            return None
        return self.db.get(ClientProfile, active_client_profile_id)

    def _format_active_client_profile(self, profile: ClientProfile) -> str:
        lines = [
            f"Активний клієнт: {profile.display_name}",
            f"Роль: {profile.matter_role}" if profile.matter_role else None,
            f"Інтереси: {profile.interests}" if profile.interests else None,
            f"Ризикові побажання: {profile.risk_preferences}" if profile.risk_preferences else None,
            (
                f"Комунікаційні побажання: {profile.communication_preferences}"
                if profile.communication_preferences
                else None
            ),
        ]
        return "\n".join(line for line in lines if line)

    def _attach_active_client_profile(
        self,
        package: N8nIntakePackage,
        event: TelegramIntakeEvent,
    ) -> None:
        binding = self._get_active_binding(event.telegram_user_id)
        if binding is None:
            return
        binding_metadata = dict(binding.metadata_json or {})
        active_client_profile_id = binding_metadata.get("active_client_profile_id")
        if not active_client_profile_id:
            return
        package_metadata = dict(package.metadata_json or {})
        package_metadata["client_profile_id"] = active_client_profile_id
        package.metadata_json = package_metadata

    def _active_client_profile_id_for_package(self, package: N8nIntakePackage) -> str | None:
        if not package.external_user_id:
            return None
        binding = self._get_active_binding(package.external_user_id)
        if binding is None:
            return None
        metadata = dict(binding.metadata_json or {})
        active_client_profile_id = metadata.get("active_client_profile_id")
        if not active_client_profile_id:
            return None
        profile = self.db.get(ClientProfile, active_client_profile_id)
        if profile is None or profile.workspace_id != package.workspace_id:
            return None
        return profile.id

    def _clear_incomplete_client_profile_draft(self, event: TelegramIntakeEvent) -> None:
        binding = self._get_active_binding(event.telegram_user_id)
        if binding is None:
            return
        metadata = dict(binding.metadata_json or {})
        onboarding_state = metadata.get("onboarding_state")
        if isinstance(onboarding_state, str) and onboarding_state.startswith("awaiting_client_"):
            metadata.pop("onboarding_state", None)
            metadata.pop("client_profile_draft", None)
            metadata.pop("client_profile_edit_id", None)
            binding.metadata_json = metadata

    def _record_client_profile_update(
        self,
        event: TelegramIntakeEvent,
        profile_id: str,
        update_type: str,
    ) -> None:
        self.audit_log_service.record(
            AuditLogCommand(
                action="n8n.telegram_client_profile_updated",
                user_id=event.user_id,
                workspace_id=event.workspace_id,
                object_type="client_profile",
                object_id=profile_id,
                metadata={"update_type": update_type, "chat_id": event.chat_id},
            ),
            commit=False,
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
            current_prompt = (
                profile.system_prompt.strip()
                if profile is not None and profile.system_prompt.strip()
                else "Системний промпт ще не створено."
            )
            return N8nIntakeResponse(
                ok=True,
                reply_text=(
                    f"Поточний системний промпт:\n{current_prompt}\n\n"
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
