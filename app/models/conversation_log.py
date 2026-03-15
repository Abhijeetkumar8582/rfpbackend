"""Conversation log model — chat/conversation message logging."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import USER_ID_LENGTH


class ConversationLog(Base):
    """
    Log of conversation/chat messages (e.g. search chat, RAG Q&A). Can be linked
    to an activity via activity_id. Messages in the same conversation share
    conversation_id.
    """
    __tablename__ = "conversation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    activity_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("activity_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # Order within conversation
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # user, assistant, system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(
        String(USER_ID_LENGTH), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Optional: model name, token counts, etc.
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<ConversationLog id={self.id} conv={self.conversation_id!r} role={self.role!r}>"
