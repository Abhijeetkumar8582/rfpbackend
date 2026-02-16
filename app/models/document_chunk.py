"""DocumentChunk model — stores split content as JSON array per document (one row per document)."""
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DocumentChunk(Base):
    """
    One row per document. content = JSON array of chunk strings.
    e.g. content = '["chunk1 text", "chunk2 text", ...]'
    GPT-generated metadata is stored here as well (mirrors documents table for chunks context).
    """
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", name="uq_document_chunks_document_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array of chunk strings
    embeddings_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of embedding arrays
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # GPT-generated metadata (same as documents table)
    doc_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    doc_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of strings
    taxonomy_suggestions_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON object

    document = relationship("Document", back_populates="chunks")

    def __repr__(self) -> str:
        return f"<DocumentChunk id={self.id} document_id={self.document_id}>"
