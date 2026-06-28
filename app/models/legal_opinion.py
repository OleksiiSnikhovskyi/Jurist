from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.types import GUID, JSONVariant, new_uuid


class LegalOpinion(Base):
    __tablename__ = "legal_opinions"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(GUID(), ForeignKey("workspaces.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    source_document_id: Mapped[str | None] = mapped_column(GUID(), ForeignKey("documents.id"))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str | None] = mapped_column(String(50))
    sources_used: Mapped[dict | None] = mapped_column(JSONVariant)
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    review_status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(GUID(), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

