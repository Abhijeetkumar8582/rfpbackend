"""Activity log model — common activity stream for all applicants (actor = user name)."""
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ActivityLog(Base):
    """
    Activity log: one row per event. Actor is the user's display name (common across
    accounts — same person logging in with different accounts is one actor).
    """
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)  # User display name (common for all applicants)
    event_action: Mapped[str] = mapped_column(String(255), nullable=False)  # e.g. "login", "upload", "view"
    target_resource: Mapped[str] = mapped_column(String(512), nullable=False, default="")  # e.g. "RFP", "Document"
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="info")  # info, warning, error, critical
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv4 or IPv6
    system: Mapped[str] = mapped_column(String(255), nullable=False, default="")  # e.g. "web", "api", "admin"

    def __repr__(self) -> str:
        return f"<ActivityLog id={self.id} actor={self.actor!r} action={self.event_action!r}>"
