"""Generate document IDs: Doc-YYYY-NNNN (e.g. Doc-2026-0001)."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document


DOCUMENT_ID_PREFIX = "Doc"
DOCUMENT_ID_LENGTH = 20  # Doc-2026-0001 = 14; 20 is safe


def generate_document_id(db: Session) -> str:
    """
    Generate next document ID for current year: Doc-YYYY-NNNN.
    NNNN is a 4-digit sequence (0001, 0002, ...) for that year.
    """
    year = datetime.now(timezone.utc).strftime("%Y")
    prefix = f"{DOCUMENT_ID_PREFIX}-{year}-"

    rows = db.execute(select(Document.id).where(Document.id.like(f"{prefix}%"))).scalars().all()
    max_seq = 0
    for (id_val,) in rows:
        try:
            num_part = id_val.split("-")[-1]
            max_seq = max(max_seq, int(num_part))
        except (ValueError, IndexError):
            pass
    next_seq = max_seq + 1
    return f"{prefix}{next_seq:04d}"
