from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.types import GUID, JSONVariant, new_uuid


class LegalSourceVerification(Base):
    __tablename__ = "legal_source_verifications"
    __table_args__ = (
        UniqueConstraint(
            "legal_source_id",
            "source_url",
            name="uq_legal_source_verifications_source",
        ),
    )

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    legal_source_id: Mapped[str | None] = mapped_column(
        GUID(),
        ForeignKey("legal_sources.id", ondelete="CASCADE"),
        nullable=True,
    )
    source_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_domain: Mapped[str | None] = mapped_column(String(255))
    source_kind: Mapped[str] = mapped_column(String(100), default="legislation", nullable=False)
    allowlist_status: Mapped[str] = mapped_column(String(50), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(100), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    final_url: Mapped[str | None] = mapped_column(String(1000))
    content_type: Mapped[str | None] = mapped_column(String(255))
    confidence: Mapped[str] = mapped_column(String(50), default="medium", nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checked_by: Mapped[str] = mapped_column(String(100), default="n8n", nullable=False)
    evidence_summary: Mapped[str | None] = mapped_column(Text)
    verification_payload: Mapped[dict | None] = mapped_column(JSONVariant)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    legal_source = relationship("LegalSource")

