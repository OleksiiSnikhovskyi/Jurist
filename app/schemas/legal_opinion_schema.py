from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


LEGAL_OPINION_REVIEW_STATUSES = frozenset({"draft", "approved", "rejected", "needs_revision"})


class LegalOpinionResponse(BaseModel):
    id: str
    workspace_id: str
    user_id: str
    source_document_id: str | None = None
    question: str
    answer: str
    risk_level: str | None = None
    sources_used: dict[str, Any] | None = None
    confidence_score: Decimal | None = None
    review_status: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class LegalOpinionReviewUpdate(BaseModel):
    user_id: str
    review_status: str = Field(pattern="^(approved|rejected|needs_revision|draft)$")
    review_notes: str | None = None


class LegalOpinionExportRequest(BaseModel):
    user_id: str
    export_format: str = Field(pattern="^(docx|pdf)$")


class LegalOpinionExportResponse(BaseModel):
    ok: bool
    export_id: str
    legal_opinion_id: str
    export_format: str
    file_path: str
    content_type: str
    file_size: int
    message: str
