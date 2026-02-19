"""
One-off migration: add answer column to search_queries (GPT/RAG answer from /search/answer).
Run from backend dir: python -m migrations.add_search_queries_answer_column
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE search_queries ADD COLUMN answer TEXT NULL"))
        except Exception as e:
            if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
                raise
        conn.commit()
    print("Migration done: search_queries.answer added")


if __name__ == "__main__":
    run()
