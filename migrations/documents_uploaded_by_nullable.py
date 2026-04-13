"""
One-off migration: allow documents.uploaded_by to be NULL so that deleting a user
keeps their uploaded documents (with uploaded_by set to NULL instead of cascading).
Also updates the FK to ON DELETE SET NULL.

Run from backend dir: python -m migrations.documents_uploaded_by_nullable
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


def run():
    dialect = engine.dialect.name
    with engine.connect() as conn:
        if dialect == "mysql":
            r = conn.execute(text("""
                SELECT CONSTRAINT_NAME
                FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'documents'
                  AND COLUMN_NAME = 'uploaded_by'
                  AND REFERENCED_TABLE_NAME = 'users'
            """)).fetchone()
            fk_name = r[0] if r else None

            if fk_name:
                conn.execute(text(
                    f"ALTER TABLE documents DROP FOREIGN KEY `{fk_name}`"
                ))

            conn.execute(text(
                "ALTER TABLE documents MODIFY COLUMN uploaded_by VARCHAR(40) NULL"
            ))

            conn.execute(text(
                "ALTER TABLE documents ADD CONSTRAINT fk_documents_uploaded_by "
                "FOREIGN KEY (uploaded_by) REFERENCES `users`(id) ON DELETE SET NULL"
            ))

            conn.commit()
            print("Migration done: documents.uploaded_by is now nullable with ON DELETE SET NULL (MySQL)")

        elif dialect == "sqlite":
            print("SQLite: no change needed if table was created from current model (uploaded_by nullable)")

        else:
            print(f"Unknown dialect {dialect}; alter documents.uploaded_by manually if needed")


if __name__ == "__main__":
    run()
