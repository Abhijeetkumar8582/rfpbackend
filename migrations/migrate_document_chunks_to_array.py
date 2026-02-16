"""
Migration: change document_chunks to one row per document, content = JSON array.
Run from backend dir: python -m migrations.migrate_document_chunks_to_array
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.begin() as conn:
        url = str(engine.url)
        # 1. Create new table
        if "sqlite" in url:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS document_chunks_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER NOT NULL UNIQUE REFERENCES documents(id) ON DELETE CASCADE,
                    content TEXT NOT NULL,
                    embeddings_json TEXT,
                    chunk_count INTEGER
                )
            """))
        elif "mysql" in url:
            # Match documents.id type (typically INT) - omit FK if types differ
            conn.execute(text("""
                CREATE TABLE document_chunks_new (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    document_id INT NOT NULL UNIQUE,
                    content LONGTEXT NOT NULL,
                    embeddings_json LONGTEXT,
                    chunk_count INT,
                    INDEX ix_document_id (document_id)
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE document_chunks_new (
                    id SERIAL PRIMARY KEY,
                    document_id INTEGER NOT NULL UNIQUE REFERENCES documents(id) ON DELETE CASCADE,
                    content TEXT NOT NULL,
                    embeddings_json TEXT,
                    chunk_count INTEGER
                )
            """))

        # 2. Migrate: group by document_id, build content array and embeddings array
        try:
            result = conn.execute(text(
                "SELECT document_id, chunk_index, content, embedding_json FROM document_chunks ORDER BY document_id, chunk_index"
            ))
            rows = result.fetchall()
        except Exception:
            try:
                result = conn.execute(text(
                    "SELECT document_id, chunk_index, content FROM document_chunks ORDER BY document_id, chunk_index"
                ))
                rows = [(r[0], r[1], r[2], None) for r in result.fetchall()]
            except Exception:
                rows = []

        # Group by document_id
        by_doc: dict[int, list[tuple[int, str, str | None]]] = {}
        for r in rows:
            doc_id, idx, cnt = r[0], r[1], r[2]
            emb = r[3] if len(r) > 3 else None
            if doc_id not in by_doc:
                by_doc[doc_id] = []
            by_doc[doc_id].append((idx, cnt, emb))

        for doc_id, items in by_doc.items():
            items.sort(key=lambda x: x[0])
            contents = [c for _, c, _ in items]
            embeddings = []
            for _, _, emb in items:
                if emb:
                    try:
                        embeddings.append(json.loads(emb))
                    except Exception:
                        pass
            content_json = json.dumps(contents)
            emb_json = json.dumps(embeddings) if embeddings else None
            chunk_count = len(contents)
            conn.execute(
                text("INSERT INTO document_chunks_new (document_id, content, embeddings_json, chunk_count) VALUES (:doc_id, :content, :emb, :cnt)"),
                {"doc_id": doc_id, "content": content_json, "emb": emb_json, "cnt": chunk_count}
            )

        # 3. Drop old, rename new
        try:
            conn.execute(text("DROP TABLE document_chunks"))
        except Exception:
            pass
        if "sqlite" in url:
            conn.execute(text("ALTER TABLE document_chunks_new RENAME TO document_chunks"))
        elif "mysql" in url:
            conn.execute(text("RENAME TABLE document_chunks_new TO document_chunks"))
        else:
            conn.execute(text("ALTER TABLE document_chunks_new RENAME TO document_chunks"))

        if "mysql" in url:
            try:
                conn.execute(text("CREATE INDEX ix_document_chunks_document_id ON document_chunks(document_id)"))
            except Exception as e:
                if "Duplicate" not in str(e):
                    raise

    print("Migration done: document_chunks now stores content as JSON array (one row per document)")


if __name__ == "__main__":
    run()
