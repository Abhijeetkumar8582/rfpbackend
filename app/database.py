"""Database engine and session — SQLAlchemy."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

# SQLite needs check_same_thread=False for FastAPI
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

# MySQL/RDS: avoid "Lost connection during query" by pinging before use and recycling old connections
engine_kwargs = {
    "connect_args": connect_args,
    "echo": settings.app_env == "development",
}
if "mysql" in settings.database_url:
    engine_kwargs["pool_pre_ping"] = True  # test connection before use; replace if dead
    engine_kwargs["pool_recycle"] = 1800   # recycle connections after 30 min (RDS often closes idle after 8h)

engine = create_engine(settings.database_url, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency: yield a DB session and close after request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
