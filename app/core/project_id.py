"""Generate project IDs: PROJ-YYYY-NNN (e.g. PROJ-2026-001)."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project


PROJECT_ID_PREFIX = "PROJ"
PROJECT_ID_LENGTH = 20  # PROJ-2026-001 = 14; 20 is safe


def generate_project_id(db: Session) -> str:
    """
    Generate next project ID for current year: PROJ-YYYY-NNN.
    NNN is a 3-digit sequence (001, 002, ...) for that year.
    """
    year = datetime.now(timezone.utc).strftime("%Y")
    prefix = f"{PROJECT_ID_PREFIX}-{year}-"

    # Fetch all ids with this prefix and compute max sequence (few projects per year)
    rows = db.execute(select(Project.id).where(Project.id.like(f"{prefix}%"))).scalars().all()
    max_seq = 0
    for (id_val,) in rows:
        try:
            num_part = id_val.split("-")[-1]
            max_seq = max(max_seq, int(num_part))
        except (ValueError, IndexError):
            pass
    next_seq = max_seq + 1
    return f"{prefix}{next_seq:03d}"
