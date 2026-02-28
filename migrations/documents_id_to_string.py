"""
One-off migration: change documents.id from INT to VARCHAR(20) for format Doc-YYYY-NNNN.
Also updates all FK columns that reference documents.id.

Run from backend dir: python -m migrations.documents_id_to_string

Note: If documents.id is currently INT, existing IDs become string equivalents (e.g. 1 -> '1').
New documents get IDs like Doc-2026-0001.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine

# Tables and columns that reference documents.id (table, column)
FK_COLUMNS = [
    ("document_chunks", "document_id"),
    ("ingestion_jobs", "document_id"),
]


def run():
    dialect = engine.dialect.name
    with engine.connect() as conn:
        if dialect == "mysql":
            # Drop FKs that reference documents.id
            for table, column in FK_COLUMNS:
                r = conn.execute(text("""
                    SELECT CONSTRAINT_NAME
                    FROM information_schema.KEY_COLUMN_USAGE
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = :t
                      AND COLUMN_NAME = :c
                      AND REFERENCED_TABLE_NAME = 'documents'
                """), {"t": table, "c": column}).fetchone()
                if r:
                    conn.execute(text(f"ALTER TABLE `{table}` DROP FOREIGN KEY `{r[0]}`"))

            # Change documents.id to VARCHAR(20) (PK already defined at table level)
            conn.execute(text("ALTER TABLE documents MODIFY COLUMN id VARCHAR(20) NOT NULL"))

            # Change each FK column to VARCHAR(20)
            for table, column in FK_COLUMNS:
                nullable = "NULL" if (table == "ingestion_jobs" and column == "document_id") else "NOT NULL"
                conn.execute(text(
                    f"ALTER TABLE `{table}` MODIFY COLUMN `{column}` VARCHAR(20) {nullable}"
                ))

            # Re-add FKs
            cascade_tables = ("document_chunks", "ingestion_jobs")
            for table, column in FK_COLUMNS:
                suffix = " ON DELETE CASCADE" if table in cascade_tables else ""
                conn.execute(text(
                    f"ALTER TABLE `{table}` ADD CONSTRAINT fk_{table}_{column} "
                    f"FOREIGN KEY (`{column}`) REFERENCES documents(id){suffix}"
                ))

            conn.commit()
            print("Migration done: documents.id and all FK columns are VARCHAR(20) (MySQL)")
        elif dialect == "sqlite":
            print("SQLite: run this only if documents.id was previously INT.")
            print("Easiest: backup data, delete rfp.db, restart app to create_all() with new schema, re-import if needed.")
        else:
            print(f"Unknown dialect {dialect}; alter documents.id and FK columns to VARCHAR(20) manually.")


if __name__ == "__main__":
    run()
