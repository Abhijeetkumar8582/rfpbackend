"""Schemas for RFP questions (rfpquestions table)."""
from datetime import datetime
import json
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _coerce_json_list(value: Any, item_type: type[str] | type[float]) -> list:
    """Accept JSON-encoded strings or Python lists and coerce to a list of desired type."""
    if value is None:
        return []
    raw = value
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    out: list = []
    for x in raw:
        try:
            out.append(item_type(x))
        except Exception:
            continue
    return out


class RFPQuestionResponse(BaseModel):
    """Single RFP row with questions and answers decoded from JSON columns."""

    id: int
    rfpid: str
    user_id: str
    name: str
    created_at: datetime
    last_activity_at: datetime
    recipients: list[str] = Field(default_factory=list, description="JSON array of recipient strings")
    status: str
    questions: list[str] = Field(default_factory=list, description="JSON array of question strings")
    answers: list[str] = Field(default_factory=list, description="JSON array of answer strings")
    confidence: list[float] = Field(default_factory=list, description="Optional confidence scores per question")

    model_config = {"from_attributes": True}

    @field_validator("recipients", mode="before")
    @classmethod
    def _coerce_recipients(cls, v):
        return _coerce_json_list(v, str)

    @field_validator("questions", mode="before")
    @classmethod
    def _coerce_questions(cls, v):
        return _coerce_json_list(v, str)

    @field_validator("answers", mode="before")
    @classmethod
    def _coerce_answers(cls, v):
        return _coerce_json_list(v, str)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, v):
        return _coerce_json_list(v, float)


class RFPQuestionListResponse(BaseModel):
    """Paginated list of RFP questions."""

    items: list[RFPQuestionResponse]
    total: int

