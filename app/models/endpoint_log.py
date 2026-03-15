"""Endpoint log model — API request/response logging with optional activity link."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.user import USER_ID_LENGTH


class EndpointLog(Base):
    """
    Log of API endpoint calls. Links to activity_logs via activity_id when the
    request is part of a tracked activity.
    """
    __tablename__ = "endpoint_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    activity_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("activity_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)  # GET, POST, PUT, PATCH, DELETE
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    actor_user_id: Mapped[str | None] = mapped_column(
        String(USER_ID_LENGTH), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_string: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    request_headers: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON object
    request_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_headers: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON object
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional relationship to activity (if you need to eager-load)
    # activity = relationship("ActivityLog", backref="endpoint_logs", foreign_keys=[activity_id])

    def __repr__(self) -> str:
        return f"<EndpointLog id={self.id} {self.method} {self.path} status={self.status_code}>"
