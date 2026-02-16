"""Schemas for the rephrase (Q&A → technical answer) API."""
from pydantic import BaseModel, Field


class RephraseRequest(BaseModel):
    """Request body: question and answer to rephrase."""

    question: str = Field(..., min_length=1, description="The original question.")
    answer: str = Field(..., min_length=1, description="The original answer to rephrase in a more technical way.")


class RephraseResponse(BaseModel):
    """Response: rephrased answer in a more technical style."""

    rephrased_answer: str = Field(..., description="The answer rephrased in a more technical way.")
