from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class N8nAttachment(BaseModel):
    type: str
    file_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    duration: int | None = None


class TelegramIntakeEvent(BaseModel):
    telegram_update_id: int | None = None
    chat_id: str
    telegram_user_id: str | None = None
    username: str | None = None
    message_id: int | None = None
    text: str | None = None
    action: str = "free_text"
    attachments: list[N8nAttachment] = Field(default_factory=list)
    has_attachments: bool = False
    workspace_id: str | None = None
    user_id: str | None = None
    requested_agent: str | None = None
    question: str | None = None
    received_at: datetime | None = None


class N8nIntakeResponse(BaseModel):
    ok: bool
    package_id: str | None = None
    status: str | None = None
    item_count: int = 0
    reply_text: str
    reply_menu: str = "main"


class N8nTelegramBindingRequest(BaseModel):
    telegram_user_id: str
    telegram_chat_id: str | None = None
    username: str | None = None
    workspace_id: str
    user_id: str
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class N8nTelegramBindingResponse(BaseModel):
    id: str
    telegram_user_id: str
    telegram_chat_id: str | None = None
    username: str | None = None
    workspace_id: str
    user_id: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class N8nProcessPackageRequest(BaseModel):
    package_id: str
    workspace_id: str | None = None
    user_id: str | None = None
    client_profile_id: str | None = None
    requested_agent: str = "orchestrator"
    question: str = "Опрацюй завантажені матеріали та підготуй юридичну відповідь."


class N8nProcessPackageResponse(BaseModel):
    ok: bool
    package_id: str
    status: str
    item_count: int
    message: str
    answer: str | None = None


class N8nExtractedTextRequest(BaseModel):
    package_id: str
    extracted_text: str = Field(min_length=1)
    item_id: str | None = None
    external_file_id: str | None = None
    workspace_id: str | None = None
    user_id: str | None = None
    file_name: str | None = None
    mime_type: str | None = None
    extraction_method: str = "external"
    document_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    auto_process: bool = False
    requested_agent: str | None = None
    question: str | None = None
    chunk_size: int = 1200
    overlap: int = 150


class N8nExtractedTextResponse(BaseModel):
    ok: bool
    package_id: str
    item_id: str
    document_id: str
    chunk_count: int
    message: str
    status: str | None = None
    answer: str | None = None


class N8nObsidianNoteRequest(BaseModel):
    workspace_id: str
    user_id: str
    note_path: str
    markdown: str
    title: str | None = None
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    sync_mode: str = "manual"
    synced_at: datetime | None = None


class N8nObsidianNoteResponse(BaseModel):
    ok: bool
    document_id: str
    chunk_count: int
    message: str

    model_config = ConfigDict(from_attributes=True)


class N8nLegalSourceUpsertRequest(BaseModel):
    workspace_id: str
    user_id: str
    source_name: str
    source_type: str = "law"
    source_url: str
    document_number: str | None = None
    adoption_date: str | None = None
    effective_date: str | None = None
    revision_date: str | None = None
    validity_status: str = "current"
    validity_note: str | None = None
    last_checked_at: datetime | None = None
    topic_tags: list[str] = Field(default_factory=list)
    summary: str | None = None
    full_text: str
    file_path: str | None = None
    jurisdiction: str = "Ukraine"
    chunk_size: int = 1200
    overlap: int = 150


class N8nLegalSourceUpsertResponse(BaseModel):
    ok: bool
    legal_source_id: str
    document_id: str
    chunk_count: int
    message: str


class N8nReembedMissingChunksRequest(BaseModel):
    batch_size: int = 16
    limit: int = 500


class N8nReembedMissingChunksResponse(BaseModel):
    ok: bool
    processed: int
    remaining_null_embeddings: int
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    message: str
