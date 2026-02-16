"""
Migration: add Name, Last activity, Recipients, Status to rfpquestions table.
Run from backend dir: python -m migrations.add_rfpquestions_name_activity_recipients_status
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        url = str(engine.url)
        # (name, sqlite_spec, mysql_spec, pg_spec). MySQL TEXT cannot have DEFAULT.
        cols = [
            ("name", "VARCHAR(512) NOT NULL DEFAULT 'Untitled RFP'", "VARCHAR(512) NOT NULL DEFAULT 'Untitled RFP'", "VARCHAR(512) NOT NULL DEFAULT 'Untitled RFP'"),
            ("last_activity_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP", "DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP", "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP"),
            ("recipients", "TEXT NOT NULL DEFAULT '[]'", "VARCHAR(2000) NOT NULL DEFAULT '[]'", "TEXT NOT NULL DEFAULT '[]'"),
            ("status", "VARCHAR(64) NOT NULL DEFAULT 'Draft'", "VARCHAR(64) NOT NULL DEFAULT 'Draft'", "VARCHAR(64) NOT NULL DEFAULT 'Draft'"),
        ]
        if "sqlite" in url:
            for col_name, col_spec, _m, _p in cols:
                try:
                    conn.execute(text(f"ALTER TABLE rfpquestions ADD COLUMN {col_name} {col_spec}"))
                except Exception as e:
                    if "duplicate column" not in str(e).lower():
                        raise
            # Set last_activity_at = created_at for existing rows
            try:
                conn.execute(text("UPDATE rfpquestions SET last_activity_at = created_at WHERE last_activity_at IS NULL"))
            except Exception:
                pass
        elif "mysql" in url:
            for col_name, _s, col_spec, _p in cols:
                try:
                    conn.execute(text(f"ALTER TABLE rfpquestions ADD COLUMN {col_name} {col_spec}"))
                except Exception as e:
                    if "1060" in str(e) or "duplicate column" in str(e).lower():
                        conn.rollback()
                    else:
                        raise
            try:
                conn.execute(text("UPDATE rfpquestions SET last_activity_at = created_at WHERE last_activity_at IS NULL OR last_activity_at = '0000-00-00 00:00:00'"))
            except Exception:
                pass
        else:
            for col_name, _s, _m, col_spec in cols:
                try:
                    conn.execute(text(f"ALTER TABLE rfpquestions ADD COLUMN {col_name} {col_spec}"))
                except Exception as e:
                    if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                        raise
            try:
                conn.execute(text("UPDATE rfpquestions SET last_activity_at = created_at WHERE last_activity_at IS NULL"))
            except Exception:
                pass
        conn.commit()
    print("Migration done: rfpquestions name, last_activity_at, recipients, status columns added")


if __name__ == "__main__":
    run()
