from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.types import GUID, JSONVariant, new_uuid


class ClientProfile(Base):
    __tablename__ = "client_profiles"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(GUID(), ForeignKey("workspaces.id"), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_type: Mapped[str | None] = mapped_column(String(100))
    matter_role: Mapped[str | None] = mapped_column(String(255))
    interests: Mapped[str | None] = mapped_column(Text)
    risk_preferences: Mapped[str | None] = mapped_column(Text)
    communication_preferences: Mapped[str | None] = mapped_column(Text)
    factual_context: Mapped[str | None] = mapped_column(Text)
    extra_context: Mapped[dict | None] = mapped_column(JSONVariant)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    workspace = relationship("Workspace")
    creator = relationship("User")
