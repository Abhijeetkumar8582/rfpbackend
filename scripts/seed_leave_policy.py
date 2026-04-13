"""Seed one leave-policy chunk into Qdrant for the first active project (local demo).

Run from `backend` with the same env as the API (PYTHONPATH, .env):

  PowerShell: $env:PYTHONPATH = (Get-Location).Path; python scripts/seed_leave_policy.py

For **embedded** storage (no Qdrant server/Docker), set in ``backend/.env``::

  QDRANT_LOCAL_PATH=.qdrant_local

Same pattern as ``Qdrant/pdf_qdrant_api.py`` with ``--path`` / ``QdrantClient(path=...)``.

Safe to re-run: upserts the same document id and chunk id in Qdrant.
"""
from __future__ import annotations

from sqlalchemy import select

from app.database import SessionLocal
from app.models.project import Project
from app.services.qdrant import add_document_chunks, delete_document_chunks

# Short HR-style text so semantic search can answer "how many leaves..."
LEAVE_CHUNK = (
    "Annual Leave Policy (Summary). Full-time employees are entitled to 24 working days of "
    "paid annual leave each calendar year. Part-time employees receive a pro-rated allowance "
    "based on their scheduled hours. Up to 5 unused days may be carried forward into the next "
    "year if approved by your manager. Leave requests should be submitted at least two weeks "
    "in advance unless there is an emergency."
)

DOC_ID = "seed_leave_policy_demo"
FILENAME = "annual_leave_policy.txt"


def main() -> int:
    db = SessionLocal()
    try:
        proj = db.execute(select(Project).where(Project.is_deleted == False)).scalars().first()
        if not proj:
            print("No active project found. Start the API once to create the default project.")
            return 1
        project_id = proj.id
    finally:
        db.close()

    delete_document_chunks(project_id, DOC_ID)
    n = add_document_chunks(
        project_id,
        DOC_ID,
        [LEAVE_CHUNK],
        filename=FILENAME,
    )
    print(f"OK project_id={project_id!r} chunks_upserted={n} doc_id={DOC_ID!r}")
    print("Try search with query_text about annual leave and this project_id.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
