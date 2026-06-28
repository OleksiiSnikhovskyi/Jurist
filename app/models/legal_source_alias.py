from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.types import GUID, new_uuid


class LegalSourceAlias(Base):
    __tablename__ = "legal_source_aliases"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str | None] = mapped_column(GUID(), ForeignKey("workspaces.id"), nullable=True)
    document_id: Mapped[str | None] = mapped_column(GUID(), ForeignKey("documents.id"), nullable=True)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_alias: Mapped[str] = mapped_column(Text, nullable=False)
    source_name: Mapped[str | None] = mapped_column(Text)
    document_number: Mapped[str | None] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
