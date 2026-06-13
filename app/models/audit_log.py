from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.types import GUID, JSONVariant, new_uuid


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    user_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    object_type: Mapped[str | None] = mapped_column(String(100))
    object_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONVariant)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
