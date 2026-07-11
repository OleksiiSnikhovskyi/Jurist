from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.types import GUID, JSONVariant, new_uuid


class OfficialSourceSearchRun(Base):
    __tablename__ = "official_source_search_runs"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(GUID(), ForeignKey("workspaces.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    trigger_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    search_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allowed_domains: Mapped[list | None] = mapped_column(JSONVariant)
    site_queries: Mapped[list | None] = mapped_column(JSONVariant)
    accepted_urls: Mapped[list | None] = mapped_column(JSONVariant)
    rejected_urls: Mapped[list | None] = mapped_column(JSONVariant)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONVariant)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
