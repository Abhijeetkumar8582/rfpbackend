"""Add sources_json and confidence_json columns to search_queries table."""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, BACKEND_ROOT)
os.chdir(BACKEND_ROOT)

from sqlalchemy import text
from app.database import engine


def main():
    """Add sources_json and confidence_json to search_queries if not present."""
    with engine.connect() as conn:
        # Detect DB type
        url = str(engine.url)
        if "sqlite" in url:
            # SQLite: JSON stored as TEXT
            for col in ("sources_json", "confidence_json"):
                try:
                    conn.execute(text(f"ALTER TABLE search_queries ADD COLUMN {col} TEXT"))
                    conn.commit()
                    print(f"Added column {col}")
                except Exception as e:
                    if "duplicate column" in str(e).lower():
                        print(f"Column {col} already exists")
                    else:
                        raise
        elif "postgresql" in url or "mysql" in url:
            try:
                conn.execute(text(
                    "ALTER TABLE search_queries ADD COLUMN sources_json JSON"
                ))
                conn.commit()
                print("Added column sources_json")
            except Exception as e:
                if "duplicate" in str(e).lower():
                    print("Column sources_json already exists")
                else:
                    raise
            try:
                conn.execute(text(
                    "ALTER TABLE search_queries ADD COLUMN confidence_json JSON"
                ))
                conn.commit()
                print("Added column confidence_json")
            except Exception as e:
                if "duplicate" in str(e).lower():
                    print("Column confidence_json already exists")
                else:
                    raise
        else:
            print("Unknown DB; run manually: ALTER TABLE search_queries ADD COLUMN sources_json JSON, ADD COLUMN confidence_json JSON")


if __name__ == "__main__":
    main()
