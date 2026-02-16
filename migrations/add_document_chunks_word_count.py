"""
Migration: add word_count column to document_chunks.
Run from backend dir: python -m migrations.add_document_chunks_word_count
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        url = str(engine.url)
        col, typ = "word_count", "INTEGER"
        if "sqlite" in url:
            try:
                conn.execute(text(f"ALTER TABLE document_chunks ADD COLUMN {col} {typ}"))
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    raise
        elif "mysql" in url:
            try:
                conn.execute(text(f"ALTER TABLE document_chunks ADD COLUMN {col} {typ}"))
            except Exception as e:
                if "duplicate" not in str(e).lower():
                    raise
        else:
            try:
                conn.execute(text(f"ALTER TABLE document_chunks ADD COLUMN {col} {typ}"))
            except Exception as e:
                if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                    raise
        conn.commit()
    print("Migration done: document_chunks.word_count added")


if __name__ == "__main__":
    run()
