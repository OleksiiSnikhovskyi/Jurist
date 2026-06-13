from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.types import GUID, JSONVariant, new_uuid


class N8nIntakePackage(Base):
    __tablename__ = "n8n_intake_packages"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str | None] = mapped_column(GUID(), ForeignKey("workspaces.id"))
    user_id: Mapped[str | None] = mapped_column(GUID(), ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    external_chat_id: Mapped[str | None] = mapped_column(String(255))
    external_user_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    requested_agent: Mapped[str | None] = mapped_column(String(100))
    question: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONVariant)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    items = relationship("N8nIntakeItem", back_populates="package")


class N8nIntakeItem(Base):
    __tablename__ = "n8n_intake_items"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    package_id: Mapped[str] = mapped_column(
        GUID(),
        ForeignKey("n8n_intake_packages.id"),
        nullable=False,
    )
    item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    external_file_id: Mapped[str | None] = mapped_column(String(500))
    file_name: Mapped[str | None] = mapped_column(String(500))
    mime_type: Mapped[str | None] = mapped_column(String(200))
    text: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONVariant)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    package = relationship("N8nIntakePackage", back_populates="items")
