"""User invitation tokens — for first-time password setup."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.user import USER_ID_LENGTH


class UserInvite(Base):
    __tablename__ = "user_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(USER_ID_LENGTH),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # JWT invite token (payload: sub, email, name, exp) sent in the set-password URL.
    token: Mapped[str] = mapped_column(String(512), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Optional: whether the invite was invalidated without being used (e.g. admin revoked)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user = relationship("User", backref="invites")

    def __repr__(self) -> str:
        return f"<UserInvite id={self.id} user_id={self.user_id}>"

