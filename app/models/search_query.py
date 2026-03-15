"""Search query model — logged searches."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import USER_ID_LENGTH


CONVERSATION_ID_LENGTH = 32  # conv_ (5) + ULID (26) = 31 chars, VARCHAR(32)


class SearchQuery(Base):
    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    datetime_: Mapped[datetime] = mapped_column("datetime", DateTime(timezone=True), nullable=False)
    # Chat grouping: same conversation_id for follow-up queries; valid 24h from first query in conversation
    conversation_id: Mapped[str] = mapped_column(String(CONVERSATION_ID_LENGTH), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(USER_ID_LENGTH), ForeignKey("users.id"), nullable=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    k: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    filters_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    results_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)  # GPT answer from /search/answer (RAG)
    topic: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Classified topic from fixed list
    sources_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # [{document_id, title, filename, ...}]
    confidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {overall, retrieval_avg_top3, ...}
    # Document metadata per source: [{document_id, title, doc_type, domain, folder_id, folder_path, uploaded_at, updated_at, status, language, tags}, ...]
    sources_document_metadata_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Gap analysis: answered | low_confidence | unanswered | needs_clarification | unsupported | contradictory
    answer_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # When answer_status != answered: no_results | low_retrieval_score | insufficient_evidence | missing_topic | language_mismatch | conflicting_sources | needs_user_clarification
    no_answer_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # User feedback: positive | negative | neutral | not_given
    feedback_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 1=helpful, 0=neutral, -1=not helpful
    feedback_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Optional: incomplete_answer | wrong_policy | missing_info | etc.
    feedback_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Optional free-text comment
    feedback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<SearchQuery id={self.id}>"
