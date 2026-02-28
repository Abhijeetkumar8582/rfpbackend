"""RFP Questions API — import questions from Excel/CSV (column A) and store in rfpquestions table."""
import csv
import io
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from openpyxl import load_workbook
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.models.rfp_question import RFPQuestion, generate_rfpid
from app.models.user import User
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rfp-questions", tags=["rfp-questions"])

@router.get("", response_model=dict)
async def list_rfp_questions(
    db: DbSession,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Max records per page"),
    user_id: str | None = Query(None, description="Filter by user ID (optional)"),
    status: str | None = Query(None, description="Filter by status (e.g. Draft, Sent)"),
):
    """
    List RFP questions with pagination.
    Returns items and total count.
    """
    q = select(RFPQuestion)
    count_q = select(func.count()).select_from(RFPQuestion)
    if user_id is not None:
        q = q.where(RFPQuestion.user_id == user_id)
        count_q = count_q.where(RFPQuestion.user_id == user_id)
    if status is not None and status.strip():
        q = q.where(RFPQuestion.status == status.strip())
        count_q = count_q.where(RFPQuestion.status == status.strip())
    total = db.execute(count_q).scalar_one()
    q = q.order_by(RFPQuestion.last_activity_at.desc()).offset(skip).limit(limit)
    rows = db.execute(q).scalars().all()
    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "rfpid": r.rfpid,
            "name": r.name,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "last_activity_at": r.last_activity_at.isoformat() if r.last_activity_at else None,
            "recipients": json.loads(r.recipients) if r.recipients else [],
            "status": r.status,
        })
    return {"items": items, "total": total}


@router.get("/{rfpid}", response_model=dict)
async def get_rfp(rfpid: str, db: DbSession):
    """Get a single RFP by rfpid (full details including questions and answers)."""
    row = db.execute(select(RFPQuestion).where(RFPQuestion.rfpid == rfpid)).scalars().one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="RFP not found")
    questions = json.loads(row.questions) if row.questions else []
    answers = json.loads(row.answers) if row.answers else []
    recipients = json.loads(row.recipients) if row.recipients else []
    return {
        "id": row.id,
        "rfpid": row.rfpid,
        "name": row.name,
        "user_id": row.user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_activity_at": row.last_activity_at.isoformat() if row.last_activity_at else None,
        "recipients": recipients,
        "status": row.status,
        "questions": questions,
        "answers": answers,
    }


@router.delete("/{rfpid}", response_model=dict)
async def delete_rfp(rfpid: str, db: DbSession):
    """Delete an RFP by rfpid. Permanently removes the record."""
    row = db.execute(select(RFPQuestion).where(RFPQuestion.rfpid == rfpid)).scalars().one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="RFP not found")
    db.delete(row)
    db.commit()
    return {"message": "RFP deleted", "rfpid": rfpid}


class UpdateAnswersBody(BaseModel):
    """Request body for updating answers array (one answer per question, same order)."""
    answers: list[str]


@router.patch("/{rfpid}/answers", response_model=dict)
async def update_rfp_answers(
    rfpid: str,
    body: UpdateAnswersBody,
    db: DbSession,
):
    """
    Update the answers array for an RFP (by rfpid).
    answers must be a list of strings, in the same order as questions.
    """
    row = db.execute(select(RFPQuestion).where(RFPQuestion.rfpid == rfpid)).scalars().one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="RFP not found")
    answers_json = json.dumps(body.answers)
    row.answers = answers_json
    row.last_activity_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "rfpid": row.rfpid,
        "id": row.id,
        "answers": body.answers,
        "last_activity_at": row.last_activity_at.isoformat() if row.last_activity_at else None,
    }


ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
ALLOWED_CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/csv",
    "application/csv",
}


def _extract_questions_from_csv(content: bytes) -> list[str]:
    """Extract column A (first column) from CSV content."""
    text = content.decode("utf-8-sig")  # utf-8-sig handles BOM
    reader = csv.reader(io.StringIO(text))
    questions: list[str] = []
    for row in reader:
        if row and row[0]:
            val = str(row[0]).strip()
            if val:
                questions.append(val)
    return questions


def _extract_questions_from_excel(content: bytes) -> list[str]:
    """Extract column A (first column) from Excel content."""
    wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    questions: list[str] = []
    for row in ws.iter_rows(min_row=1, max_col=1):
        cell = row[0]
        if cell.value is not None:
            val = str(cell.value).strip()
            if val:
                questions.append(val)
    return questions


def _extract_questions(file: UploadFile, body: bytes) -> list[str]:
    """Extract questions from Excel or CSV file (column A)."""
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()

    if filename.endswith(".csv") or "csv" in content_type:
        return _extract_questions_from_csv(body)
    if filename.endswith((".xlsx", ".xls")) or "spreadsheet" in content_type or "excel" in content_type:
        return _extract_questions_from_excel(body)

    # Fallback by extension
    if any(filename.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        if ".csv" in filename:
            return _extract_questions_from_csv(body)
        return _extract_questions_from_excel(body)

    raise HTTPException(
        status_code=400,
        detail="Unsupported file format. Use Excel (.xlsx, .xls) or CSV.",
    )


@router.post("/import", response_model=dict)
async def import_questions(
    db: DbSession,
    user_id: str = Form(..., description="User ID (UUID) who is importing"),
    file: UploadFile = File(..., description="Excel or CSV file with questions in column A"),
):
    """
    Import questions from Excel or CSV.
    Extracts column A as list of questions, generates rfpid, and stores in rfpquestions table.
    """
    logger.info("RFP questions import: filename=%s user_id=%s", file.filename, user_id)

    # Validate user exists
    user = db.execute(select(User).where(User.id == user_id)).scalars().one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    body = await file.read()
    if not body:
        raise HTTPException(status_code=400, detail="File is empty")

    questions = _extract_questions(file, body)
    if not questions:
        raise HTTPException(status_code=400, detail="No questions found in column A")

    rfpid = generate_rfpid()
    now = datetime.now(timezone.utc)
    name = (file.filename or "Untitled RFP").rsplit(".", 1)[0]  # strip extension
    if not name.strip():
        name = "Untitled RFP"
    questions_json = json.dumps(questions)
    answers_json = json.dumps([])
    recipients_json = json.dumps([])

    record = RFPQuestion(
        rfpid=rfpid,
        user_id=user_id,
        name=name[:512],
        created_at=now,
        last_activity_at=now,
        recipients=recipients_json,
        status="Draft",
        questions=questions_json,
        answers=answers_json,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "rfpid": rfpid,
        "id": record.id,
        "name": record.name,
        "question_count": len(questions),
        "last_activity_at": record.last_activity_at.isoformat() if record.last_activity_at else None,
        "recipients": json.loads(record.recipients) if record.recipients else [],
        "status": record.status,
    }
