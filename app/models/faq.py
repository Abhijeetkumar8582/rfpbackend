"""FAQ model — user-provided Q&A from Intelligence Hub (Review gaps)."""
import uuid
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FAQ(Base):
    __tablename__ = "FAQs"

    faqId: Mapped[str] = mapped_column(
        "faqId",
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
