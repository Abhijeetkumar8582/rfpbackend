"""Per-user KB / search balance preferences (Text / Vector / Rerank weights)."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import USER_ID_LENGTH


class UserKbSettings(Base):
    """Stores Search balance percentages for the RFP Assistant (must sum to 100)."""

    __tablename__ = "user_kb_settings"

    user_id: Mapped[str] = mapped_column(
        String(USER_ID_LENGTH),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    text_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    vector_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    rerank_pct: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return f"<UserKbSettings user_id={self.user_id} text={self.text_pct} vector={self.vector_pct} rerank={self.rerank_pct}>"
