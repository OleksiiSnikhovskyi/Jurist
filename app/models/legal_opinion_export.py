from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.types import GUID, JSONVariant, new_uuid


class LegalOpinionExport(Base):
    __tablename__ = "legal_opinion_exports"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    legal_opinion_id: Mapped[str] = mapped_column(
        GUID(),
        ForeignKey("legal_opinions.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[str] = mapped_column(GUID(), ForeignKey("workspaces.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    exported_by: Mapped[str] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    export_format: Mapped[str] = mapped_column(String(20), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONVariant)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
