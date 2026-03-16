"""Document access log model — who accessed which document (view, download, upload) for Access Intelligence."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import USER_ID_LENGTH

# UUID string length (e.g. 36 for "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
ACCESS_LOG_ID_LENGTH = 36


class DocumentAccessLog(Base):
    """
    Log of document access events: view, download, upload.
    Used by Access Intelligence and File Repository integration.
    """
    __tablename__ = "document_access_logs"

    id: Mapped[str] = mapped_column(String(ACCESS_LOG_ID_LENGTH), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String(USER_ID_LENGTH),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    date_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    document_name: Mapped[str] = mapped_column(String(512), nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    access_level: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)

    def __repr__(self) -> str:
        return f"<DocumentAccessLog id={self.id} user={self.username} doc={self.document_name} action={self.action}>"
