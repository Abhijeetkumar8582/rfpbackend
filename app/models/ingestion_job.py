"""Ingestion job model — document processing pipeline."""
from datetime import datetime
import enum
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class IngestionJobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    status: Mapped[IngestionJobStatus] = mapped_column(Enum(IngestionJobStatus), nullable=False, default=IngestionJobStatus.pending)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    project = relationship("Project", back_populates="ingestion_jobs")
    document = relationship("Document", back_populates="ingestion_jobs")

    def __repr__(self) -> str:
        return f"<IngestionJob id={self.id} status={self.status}>"
