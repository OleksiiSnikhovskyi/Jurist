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


class N8nProcessPackageRequest(BaseModel):
    package_id: str
    workspace_id: str | None = None
    user_id: str | None = None
    requested_agent: str = "orchestrator"
    question: str = "Опрацюй завантажені матеріали та підготуй юридичну відповідь."


class N8nProcessPackageResponse(BaseModel):
    ok: bool
    package_id: str
    status: str
    item_count: int
    message: str


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
