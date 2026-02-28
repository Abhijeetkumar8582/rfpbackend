"""Search query model — logged searches."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.project import PROJECT_ID_LENGTH
from app.models.user import USER_ID_LENGTH


class SearchQuery(Base):
    __tablename__ = "search_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(String(USER_ID_LENGTH), ForeignKey("users.id"), nullable=True)
    project_id: Mapped[str] = mapped_column(String(PROJECT_ID_LENGTH), ForeignKey("projects.id"), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    k: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    filters_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    results_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)  # GPT answer from /search/answer (RAG)
    topic: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Classified topic from fixed list

    def __repr__(self) -> str:
        return f"<SearchQuery id={self.id} project_id={self.project_id}>"
