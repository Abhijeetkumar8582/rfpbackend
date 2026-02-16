"""
Migration: create activity_logs table (Timestamp, Actor, Event Action, Target Resource, Severity, Ipaddress, System).
Run from backend dir: python -m migrations.activity_logs_table
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        url = str(engine.url)
        # Drop existing table if it has old schema (optional; comment out to preserve data)
        try:
            conn.execute(text("DROP TABLE IF EXISTS activity_logs"))
        except Exception:
            pass

        if "sqlite" in url:
            conn.execute(text("""
                CREATE TABLE activity_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP NOT NULL,
                    actor VARCHAR(255) NOT NULL,
                    event_action VARCHAR(255) NOT NULL,
                    target_resource VARCHAR(512) NOT NULL DEFAULT '',
                    severity VARCHAR(32) NOT NULL DEFAULT 'info',
                    ip_address VARCHAR(45),
                    system VARCHAR(255) NOT NULL DEFAULT ''
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_activity_logs_timestamp ON activity_logs(timestamp)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_activity_logs_actor ON activity_logs(actor)"))
        elif "mysql" in url:
            conn.execute(text("""
                CREATE TABLE activity_logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    timestamp DATETIME NOT NULL,
                    actor VARCHAR(255) NOT NULL,
                    event_action VARCHAR(255) NOT NULL,
                    target_resource VARCHAR(512) NOT NULL DEFAULT '',
                    severity VARCHAR(32) NOT NULL DEFAULT 'info',
                    ip_address VARCHAR(45),
                    `system` VARCHAR(255) NOT NULL DEFAULT '',
                    KEY ix_activity_logs_timestamp (timestamp),
                    KEY ix_activity_logs_actor (actor)
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE activity_logs (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                    actor VARCHAR(255) NOT NULL,
                    event_action VARCHAR(255) NOT NULL,
                    target_resource VARCHAR(512) NOT NULL DEFAULT '',
                    severity VARCHAR(32) NOT NULL DEFAULT 'info',
                    ip_address VARCHAR(45),
                    system VARCHAR(255) NOT NULL DEFAULT ''
                )
            """))
            conn.execute(text("CREATE INDEX ix_activity_logs_timestamp ON activity_logs(timestamp)"))
            conn.execute(text("CREATE INDEX ix_activity_logs_actor ON activity_logs(actor)"))
        conn.commit()
    print("Migration done: activity_logs table created")


if __name__ == "__main__":
    run()
