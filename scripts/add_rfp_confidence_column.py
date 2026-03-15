#!/usr/bin/env python3
"""
Add confidence column to rfpquestions table (MySQL) if missing.
Stores a JSON array of numbers (one per question, same row order).
Run from backend dir: python scripts/add_rfp_confidence_column.py
"""
import os
import sys

# Add backend app to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.database import engine
from app.config import settings


def main():
    is_mysql = "mysql" in (settings.database_url or "")
    if is_mysql:
        sql = "ALTER TABLE rfpquestions ADD COLUMN confidence JSON"
    else:
        sql = "ALTER TABLE rfpquestions ADD COLUMN confidence TEXT NOT NULL DEFAULT '[]'"

    with engine.connect() as conn:
        try:
            conn.execute(text(sql))
            conn.commit()
            print("Added column rfpquestions.confidence.")
        except Exception as e:
            err_msg = str(e).lower()
            if "duplicate column" in err_msg or "1060" in str(e):
                conn.rollback()
                print("Column rfpquestions.confidence already exists; nothing to do.")
            else:
                raise


if __name__ == "__main__":
    main()
