from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.types import GUID, new_uuid


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    workspace_id: Mapped[str] = mapped_column(GUID(), ForeignKey("workspaces.id"), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(GUID(), ForeignKey("users.id"), nullable=False)
    document_name: Mapped[str] = mapped_column(String(500), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(100))
    file_path: Mapped[str | None] = mapped_column(String(1000))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    confidentiality_level: Mapped[str] = mapped_column(String(50), default="private", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workspace = relationship("Workspace", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(GUID(), ForeignKey("documents.id"), nullable=False)
    workspace_id: Mapped[str] = mapped_column(GUID(), ForeignKey("workspaces.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document", back_populates="chunks")

