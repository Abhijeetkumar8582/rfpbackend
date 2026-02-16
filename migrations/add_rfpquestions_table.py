"""
Migration: create rfpquestions table.
Run from backend dir: python -m migrations.add_rfpquestions_table
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
                CREATE TABLE IF NOT EXISTS rfpquestions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rfpid VARCHAR(36) NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name VARCHAR(512) NOT NULL DEFAULT 'Untitled RFP',
                    created_at TIMESTAMP NOT NULL,
                    last_activity_at TIMESTAMP NOT NULL,
                    recipients TEXT NOT NULL DEFAULT '[]',
                    status VARCHAR(64) NOT NULL DEFAULT 'Draft',
                    questions TEXT NOT NULL,
                    answers TEXT NOT NULL
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rfpquestions_rfpid ON rfpquestions(rfpid)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rfpquestions_user_id ON rfpquestions(user_id)"))
        elif "mysql" in url:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS rfpquestions (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    rfpid VARCHAR(36) NOT NULL,
                    user_id BIGINT NOT NULL,
                    name VARCHAR(512) NOT NULL DEFAULT 'Untitled RFP',
                    created_at DATETIME NOT NULL,
                    last_activity_at DATETIME NOT NULL,
                    recipients VARCHAR(2000) NOT NULL DEFAULT '[]',
                    status VARCHAR(64) NOT NULL DEFAULT 'Draft',
                    questions TEXT NOT NULL,
                    answers TEXT NOT NULL,
                    UNIQUE KEY uq_rfpquestions_rfpid (rfpid),
                    KEY ix_rfpquestions_rfpid (rfpid),
                    KEY ix_rfpquestions_user_id (user_id),
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS rfpquestions (
                    id SERIAL PRIMARY KEY,
                    rfpid VARCHAR(36) NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name VARCHAR(512) NOT NULL DEFAULT 'Untitled RFP',
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    last_activity_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    recipients TEXT NOT NULL DEFAULT '[]',
                    status VARCHAR(64) NOT NULL DEFAULT 'Draft',
                    questions TEXT NOT NULL,
                    answers TEXT NOT NULL
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rfpquestions_rfpid ON rfpquestions(rfpid)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rfpquestions_user_id ON rfpquestions(user_id)"))
        conn.commit()
    print("Migration done: rfpquestions table created")


if __name__ == "__main__":
    run()
