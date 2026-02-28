"""
One-off migration: change projects.id from INT to VARCHAR(20) for format PROJ-YYYY-NNN.
Also updates all FK columns that reference projects.id.

Run from backend dir: python -m migrations.projects_id_to_string

Note: If projects.id is currently INT, existing IDs become string equivalents (e.g. 1 -> '1').
New projects get IDs like PROJ-2026-001.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine

# Tables and columns that reference projects.id (table, column)
FK_COLUMNS = [
    ("project_members", "project_id"),
    ("documents", "project_id"),
    ("search_queries", "project_id"),
    ("audit_logs", "project_id"),
    ("ingestion_jobs", "project_id"),
]


def run():
    dialect = engine.dialect.name
    with engine.connect() as conn:
        if dialect == "mysql":
            # Drop FKs that reference projects.id
            for table, column in FK_COLUMNS:
                r = conn.execute(text("""
                    SELECT CONSTRAINT_NAME
                    FROM information_schema.KEY_COLUMN_USAGE
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = :t
                      AND COLUMN_NAME = :c
                      AND REFERENCED_TABLE_NAME = 'projects'
                """), {"t": table, "c": column}).fetchone()
                if r:
                    conn.execute(text(f"ALTER TABLE `{table}` DROP FOREIGN KEY `{r[0]}`"))

            # Change projects.id to VARCHAR(20) (PK already defined at table level)
            conn.execute(text("ALTER TABLE projects MODIFY COLUMN id VARCHAR(20) NOT NULL"))

            # Change each FK column to VARCHAR(20)
            for table, column in FK_COLUMNS:
                nullable = "NULL" if (table == "audit_logs" and column == "project_id") else "NOT NULL"
                conn.execute(text(
                    f"ALTER TABLE `{table}` MODIFY COLUMN `{column}` VARCHAR(20) {nullable}"
                ))

            # Re-add FKs
            cascade_tables = ("project_members", "documents", "search_queries", "ingestion_jobs")
            for table, column in FK_COLUMNS:
                suffix = " ON DELETE CASCADE" if table in cascade_tables else ""
                conn.execute(text(
                    f"ALTER TABLE `{table}` ADD CONSTRAINT fk_{table}_{column} "
                    f"FOREIGN KEY (`{column}`) REFERENCES projects(id){suffix}"
                ))

            conn.commit()
            print("Migration done: projects.id and all FK columns are VARCHAR(20) (MySQL)")
        elif dialect == "sqlite":
            print("SQLite: run this only if projects.id was previously INT.")
            print("Easiest: backup data, delete rfp.db, restart app to create_all() with new schema, re-import if needed.")
        else:
            print(f"Unknown dialect {dialect}; alter projects.id and FK columns to VARCHAR(20) manually.")


if __name__ == "__main__":
    run()
