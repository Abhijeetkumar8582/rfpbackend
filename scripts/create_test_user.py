"""Create a local test user (email/password in constants below).

From repo `backend` folder (use the same Python as your venv, with pymysql installed):

  PowerShell: $env:PYTHONPATH = (Get-Location).Path; python scripts/create_test_user.py

Safe to re-run: skips if the email already exists.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.core.security import hash_password
from app.core.user_id import generate_user_id
from app.models.user import User, UserRole

EMAIL = "abhijeet122kumar@gmail.com"
PASSWORD = "1234"


def main() -> None:
    db = SessionLocal()
    try:
        existing = db.execute(select(User).where(User.email == EMAIL)).scalars().first()
        if existing:
            print("User already exists:", existing.id, existing.email)
            return
        u = User(
            id=generate_user_id(),
            email=EMAIL,
            name="Test User",
            password_hash=hash_password(PASSWORD),
            role=UserRole.viewer,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(u)
        db.commit()
        print("Created user:", u.id, u.email)
    finally:
        db.close()


if __name__ == "__main__":
    main()
