"""Document model — project files and ingestion status."""
import enum
import uuid
from datetime import datetime
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.types import Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DocumentStatus(str, enum.Enum):
    pending = "pending"
    ingesting = "ingesting"
    ingested = "ingested"
    failed = "failed"
    deleted = "deleted"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(Enum(DocumentStatus), nullable=False, default=DocumentStatus.pending)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Auto-categorization (cluster) and vector embedding for file repo / search
    cluster: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # GPT-generated metadata (title, description, doc_type, tags, taxonomy_suggestions)
    doc_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    doc_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of strings
    taxonomy_suggestions_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON object

    project = relationship("Project", back_populates="documents")
    uploaded_by_user = relationship("User", back_populates="uploaded_documents", foreign_keys=[uploaded_by])
    ingestion_jobs = relationship("IngestionJob", back_populates="document", cascade="all, delete-orphan")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Document id={self.id} filename={self.filename}>"
