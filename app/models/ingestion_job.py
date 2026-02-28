"""Ingestion job model — document processing pipeline."""
from datetime import datetime
import enum
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.document import DOCUMENT_ID_LENGTH
from app.models.project import PROJECT_ID_LENGTH


class IngestionJobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(PROJECT_ID_LENGTH), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(DOCUMENT_ID_LENGTH), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    status: Mapped[IngestionJobStatus] = mapped_column(Enum(IngestionJobStatus), nullable=False, default=IngestionJobStatus.pending)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    project = relationship("Project", back_populates="ingestion_jobs")
    document = relationship("Document", back_populates="ingestion_jobs")

    def __repr__(self) -> str:
        return f"<IngestionJob id={self.id} status={self.status}>"
