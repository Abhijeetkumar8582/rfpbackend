"""RFPQuestion model — stores RFP questions/answers from Excel/CSV import."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def generate_rfpid() -> str:
    """Generate a unique RFP ID (UUID4)."""
    return str(uuid.uuid4())


class RFPQuestion(Base):
    """
    Stores RFP questions imported from Excel/CSV.
    - questions: JSON array of question strings (from column A)
    - answers: JSON array (initially empty, populated later)
    """
    __tablename__ = "rfpquestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rfpid: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False, default=generate_rfpid)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False, default="Untitled RFP")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recipients: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON array of recipient strings
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="Draft")  # Draft, Sent, Viewed, etc.
    questions: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array of question strings
    answers: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON array (initially empty)

    user = relationship("User", back_populates="rfp_questions")

    def __repr__(self) -> str:
        return f"<RFPQuestion id={self.id} rfpid={self.rfpid}>"
