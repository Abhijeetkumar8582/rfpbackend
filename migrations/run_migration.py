"""
Run SQL migrations against the configured database.
Usage (from backend/):  python migrations/run_migration.py [migration_name]
Example:  python migrations/run_migration.py search_queries_ts_to_datetime_drop_project_id
If no name is given, runs search_queries_ts_to_datetime_drop_project_id.
"""
import sys
from pathlib import Path

# Ensure backend app is importable when run as: python migrations/run_migration.py
_backend_root = Path(__file__).resolve().parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from sqlalchemy import text
from app.database import engine
from app.config import settings


def run_search_queries_ts_to_datetime_drop_project_id():
    """Rename ts -> datetime and drop project_id on search_queries."""
    url = settings.database_url
    if "sqlite" in url:
        stmts = [
            "ALTER TABLE search_queries RENAME COLUMN ts TO datetime",
            "ALTER TABLE search_queries DROP COLUMN project_id",
        ]
    elif "mysql" in url:
        # MySQL: drop FK constraint before dropping the column
        stmts = [
            "ALTER TABLE search_queries RENAME COLUMN ts TO datetime",
            "ALTER TABLE search_queries DROP FOREIGN KEY fk_search_queries_project_id",
            "ALTER TABLE search_queries DROP COLUMN project_id",
        ]
    else:
        # PostgreSQL: drop constraint first (name may vary; check information_schema if needed)
        stmts = [
            "ALTER TABLE search_queries RENAME COLUMN ts TO datetime",
            "ALTER TABLE search_queries DROP CONSTRAINT IF EXISTS search_queries_project_id_fkey",
            "ALTER TABLE search_queries DROP COLUMN project_id",
        ]
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))
            print(f"  OK: {s[:60]}..." if len(s) > 60 else f"  OK: {s}")


def run_search_queries_drop_project_id_only():
    """Drop project_id and its FK (use if ts was already renamed to datetime)."""
    url = settings.database_url
    if "mysql" in url:
        stmts = [
            "ALTER TABLE search_queries DROP FOREIGN KEY fk_search_queries_project_id",
            "ALTER TABLE search_queries DROP COLUMN project_id",
        ]
    elif "postgresql" in url or "postgres" in url:
        stmts = [
            "ALTER TABLE search_queries DROP CONSTRAINT IF EXISTS search_queries_project_id_fkey",
            "ALTER TABLE search_queries DROP COLUMN project_id",
        ]
    else:
        stmts = ["ALTER TABLE search_queries DROP COLUMN project_id"]
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))
            print(f"  OK: {s[:60]}..." if len(s) > 60 else f"  OK: {s}")


def run_add_conversation_id():
    """Add conversation_id to search_queries (after datetime)."""
    url = settings.database_url
    if "sqlite" in url:
        stmts = [
            "ALTER TABLE search_queries ADD COLUMN conversation_id VARCHAR(32) NOT NULL DEFAULT 'conv_LEGACY0000000000000000'",
        ]
    elif "mysql" in url:
        stmts = [
            "ALTER TABLE search_queries ADD COLUMN conversation_id VARCHAR(32) NOT NULL DEFAULT 'conv_LEGACY0000000000000000' AFTER datetime",
        ]
    else:
        stmts = [
            "ALTER TABLE search_queries ADD COLUMN conversation_id VARCHAR(32)",
            "UPDATE search_queries SET conversation_id = 'conv_LEGACY' || id WHERE conversation_id IS NULL",
            "ALTER TABLE search_queries ALTER COLUMN conversation_id SET NOT NULL",
        ]
    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))
            print(f"  OK: {s[:60]}..." if len(s) > 60 else f"  OK: {s}")


MIGRATIONS = {
    "search_queries_ts_to_datetime_drop_project_id": run_search_queries_ts_to_datetime_drop_project_id,
    "search_queries_drop_project_id_only": run_search_queries_drop_project_id_only,
    "add_conversation_id": run_add_conversation_id,
}


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "search_queries_ts_to_datetime_drop_project_id"
    if name not in MIGRATIONS:
        print(f"Unknown migration: {name}")
        print(f"Available: {', '.join(MIGRATIONS)}")
        sys.exit(1)
    print(f"Running migration: {name}")
    MIGRATIONS[name]()
    print("Done.")


if __name__ == "__main__":
    main()
