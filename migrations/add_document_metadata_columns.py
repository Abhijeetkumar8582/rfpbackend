"""
One-off migration: add GPT-generated metadata columns to documents table.
Run from backend dir: python -m migrations.add_document_metadata_columns
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        columns = [
            ("doc_title", "VARCHAR(256)"),
            ("doc_description", "TEXT"),
            ("doc_type", "VARCHAR(64)"),
            ("tags_json", "TEXT"),
            ("taxonomy_suggestions_json", "TEXT"),
        ]
        for col, typ in columns:
            try:
                conn.execute(text(f"ALTER TABLE documents ADD COLUMN {col} {typ}"))
            except Exception as e:
                if "duplicate column" not in str(e).lower() and "already exists" not in str(e).lower():
                    raise
        conn.commit()
    print("Migration done: documents.doc_title, doc_description, doc_type, tags_json, taxonomy_suggestions_json")


if __name__ == "__main__":
    run()
