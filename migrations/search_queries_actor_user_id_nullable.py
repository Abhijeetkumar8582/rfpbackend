"""
One-off migration: allow search_queries.actor_user_id to be NULL (for unauthenticated search logging).
Run from backend dir: python -m migrations.search_queries_actor_user_id_nullable
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
            # Find the actual FK constraint name (RDS/MySQL may use auto-generated names)
            r = conn.execute(text("""
                SELECT CONSTRAINT_NAME
                FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = 'search_queries'
                  AND COLUMN_NAME = 'actor_user_id'
                  AND REFERENCED_TABLE_NAME = 'users'
            """)).fetchone()
            fk_name = r[0] if r else None
            if fk_name:
                conn.execute(text(
                    f"ALTER TABLE search_queries DROP FOREIGN KEY `{fk_name}`"
                ))
            conn.execute(text(
                "ALTER TABLE search_queries MODIFY COLUMN actor_user_id INT NULL"
            ))
            if fk_name:
                conn.execute(text(
                    "ALTER TABLE search_queries ADD CONSTRAINT fk_search_queries_actor "
                    "FOREIGN KEY (actor_user_id) REFERENCES users(id)"
                ))
            conn.commit()
            print("Migration done: search_queries.actor_user_id is now nullable (MySQL)")
        elif dialect == "sqlite":
            # SQLite doesn't support MODIFY COLUMN; table created from current model is already nullable
            print("SQLite: no change needed if table was created from current model (actor_user_id nullable)")
        else:
            print(f"Unknown dialect {dialect}; alter search_queries.actor_user_id to NULL manually if needed")


if __name__ == "__main__":
    run()
