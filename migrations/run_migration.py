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


def run_create_api_credentials():
    """Create api_credentials table for storing encrypted API credentials."""
    url = settings.database_url

    if "sqlite" in url:
        # SQLite: no native JSON type; store JSON as TEXT.
        # updated_at auto-update must be handled by app logic or triggers (not added here).
        stmts = [
            """
            CREATE TABLE IF NOT EXISTS api_credentials (
              id              VARCHAR(36) PRIMARY KEY,
              tenant_id       VARCHAR(36) NOT NULL,
              api_name        VARCHAR(255) NOT NULL,
              api_url         VARCHAR(1000),
              secret_key_1    TEXT,
              secret_key_2    TEXT,
              secret_key_3    TEXT,
              secret_key_4    TEXT,
              secret_key_5    TEXT,
              parameter_json  TEXT,
              status          VARCHAR(50) NOT NULL DEFAULT 'active',
              created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_api_credentials_tenant ON api_credentials(tenant_id)",
        ]
    elif "mysql" in url:
        stmts = [
            """
            CREATE TABLE IF NOT EXISTS api_credentials (
              id              CHAR(36) PRIMARY KEY,
              tenant_id       CHAR(36) NOT NULL,
              api_name        VARCHAR(255) NOT NULL,
              api_url         VARCHAR(1000) NULL,
              secret_key_1    TEXT NULL,
              secret_key_2    TEXT NULL,
              secret_key_3    TEXT NULL,
              secret_key_4    TEXT NULL,
              secret_key_5    TEXT NULL,
              parameter_json  JSON NULL,
              status          VARCHAR(50) NOT NULL DEFAULT 'active',
              created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              INDEX idx_api_credentials_tenant (tenant_id)
            )
            """,
        ]
    else:
        # PostgreSQL: use JSONB + trigger-less updated_at default.
        stmts = [
            """
            CREATE TABLE IF NOT EXISTS api_credentials (
              id              VARCHAR(36) PRIMARY KEY,
              tenant_id       VARCHAR(36) NOT NULL,
              api_name        VARCHAR(255) NOT NULL,
              api_url         VARCHAR(1000),
              secret_key_1    TEXT,
              secret_key_2    TEXT,
              secret_key_3    TEXT,
              secret_key_4    TEXT,
              secret_key_5    TEXT,
              parameter_json  JSONB,
              status          VARCHAR(50) NOT NULL DEFAULT 'active',
              created_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_api_credentials_tenant ON api_credentials(tenant_id)",
        ]

    with engine.begin() as conn:
        for s in stmts:
            conn.execute(text(s))
            preview = " ".join(s.split())
            print(f"  OK: {preview[:60]}..." if len(preview) > 60 else f"  OK: {preview}")


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
    "create_api_credentials": run_create_api_credentials,
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
