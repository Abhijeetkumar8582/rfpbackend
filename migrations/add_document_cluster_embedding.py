"""
One-off migration: add cluster and embedding_json to documents table.
Run from backend dir: python -m migrations.add_document_cluster_embedding
"""
import os
import sys

# Allow importing app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine

def run():
    with engine.connect() as conn:
        # SQLite
        if "sqlite" in str(engine.url):
            try:
                conn.execute(text("ALTER TABLE documents ADD COLUMN cluster VARCHAR(128)"))
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    raise
            try:
                conn.execute(text("ALTER TABLE documents ADD COLUMN embedding_json TEXT"))
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    raise
        else:
            # MySQL / PostgreSQL — run once; ignore if columns already exist
            for col, typ in (("cluster", "VARCHAR(128)"), ("embedding_json", "TEXT")):
                try:
                    conn.execute(text(f"ALTER TABLE documents ADD COLUMN {col} {typ}"))
                except Exception as e:
                    if "duplicate" not in str(e).lower() and "already exists" not in str(e).lower():
                        raise
        conn.commit()
    print("Migration done: documents.cluster, documents.embedding_json")

if __name__ == "__main__":
    run()
