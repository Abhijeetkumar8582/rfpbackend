"""
One-off migration: add topic column to search_queries (classified topic from RAG answer).
Run from backend dir: python -m migrations.add_search_queries_topic_column
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE search_queries ADD COLUMN topic VARCHAR(64) NULL"))
        except Exception as e:
            if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
                raise
        conn.commit()
    print("Migration done: search_queries.topic added")


if __name__ == "__main__":
    run()
