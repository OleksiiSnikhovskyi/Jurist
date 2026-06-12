from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.types import GUID, new_uuid


class LawyerProfile(Base):
    __tablename__ = "lawyer_profiles"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    specialization: Mapped[str | None] = mapped_column(Text)
    jurisdictions: Mapped[list[str] | None] = mapped_column(JSONB)
    workplace_context: Mapped[str | None] = mapped_column(Text)
    represented_interests: Mapped[str | None] = mapped_column(Text)
    communication_style: Mapped[str | None] = mapped_column(Text)
    extra_context: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user = relationship("User", back_populates="lawyer_profile")
