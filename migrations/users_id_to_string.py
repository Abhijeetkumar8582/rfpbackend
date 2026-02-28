"""
One-off migration: change users.id from INT/UUID to VARCHAR(40) for custom ID format
(10-char UUID prefix + '-' + DDMMYYYYHHMMSS). Also updates all FK columns that reference users.id.

Run from backend dir: python -m migrations.users_id_to_string

Note: If users.id is currently INT, existing IDs become string equivalents (e.g. 4 -> '4').
New users get IDs like U8189cf674-19022026155529.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine

# Tables and columns that reference users.id (table, column)
FK_COLUMNS = [
    ("refresh_tokens", "user_id"),
    ("documents", "uploaded_by"),
    ("project_members", "user_id"),
    ("rfpquestions", "user_id"),
    ("search_queries", "actor_user_id"),
    ("audit_logs", "actor_user_id"),
]


def run():
    dialect = engine.dialect.name
    with engine.connect() as conn:
        if dialect == "mysql":
            # Drop FKs that reference users.id
            for table, column in FK_COLUMNS:
                r = conn.execute(text("""
                    SELECT CONSTRAINT_NAME
                    FROM information_schema.KEY_COLUMN_USAGE
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = :t
                      AND COLUMN_NAME = :c
                      AND REFERENCED_TABLE_NAME = 'users'
                """), {"t": table, "c": column}).fetchone()
                if r:
                    conn.execute(text(f"ALTER TABLE `{table}` DROP FOREIGN KEY `{r[0]}`"))

            # Change users.id to VARCHAR(40) (PK already defined at table level)
            conn.execute(text("ALTER TABLE users MODIFY COLUMN id VARCHAR(40) NOT NULL"))

            # Change each FK column to VARCHAR(40)
            for table, column in FK_COLUMNS:
                nullable = "NULL" if column == "actor_user_id" else "NOT NULL"
                conn.execute(text(
                    f"ALTER TABLE `{table}` MODIFY COLUMN `{column}` VARCHAR(40) {nullable}"
                ))

            # Re-add FKs
            cascade_tables = ("refresh_tokens", "project_members", "rfpquestions")
            for table, column in FK_COLUMNS:
                suffix = " ON DELETE CASCADE" if table in cascade_tables else ""
                conn.execute(text(
                    f"ALTER TABLE `{table}` ADD CONSTRAINT fk_{table}_{column} "
                    f"FOREIGN KEY (`{column}`) REFERENCES users(id){suffix}"
                ))

            conn.commit()
            print("Migration done: users.id and all FK columns are VARCHAR(40) (MySQL)")
        elif dialect == "sqlite":
            # SQLite: cannot change column type in place. Would require recreate table.
            # If DB was created with create_all() after this code change, tables already have correct types.
            print("SQLite: run this only if users.id was previously INT/UUID.")
            print("Easiest: backup data, delete rfp.db, restart app to create_all() with new schema, re-import if needed.")
        else:
            print(f"Unknown dialect {dialect}; alter users.id and FK columns to VARCHAR(40) manually.")


if __name__ == "__main__":
    run()
