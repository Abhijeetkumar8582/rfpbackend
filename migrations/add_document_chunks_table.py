"""
Migration: create document_chunks table.
Run from backend dir: python -m migrations.add_document_chunks_table
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        url = str(engine.url)
        if "sqlite" in url:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_document_chunks_document_id ON document_chunks(document_id)"))
        elif "mysql" in url:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    document_id INT NOT NULL,
                    chunk_index INT NOT NULL,
                    content TEXT NOT NULL,
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
                )
            """))
            try:
                conn.execute(text("CREATE INDEX ix_document_chunks_document_id ON document_chunks(document_id)"))
            except Exception as e:
                if "Duplicate key name" not in str(e):
                    raise
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id SERIAL PRIMARY KEY,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_document_chunks_document_id ON document_chunks(document_id)"))
        conn.commit()
    print("Migration done: document_chunks table created")


if __name__ == "__main__":
    run()
