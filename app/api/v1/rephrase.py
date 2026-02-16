"""Rephrase API — rephrase an answer in a more technical way given question and answer."""
from fastapi import APIRouter, HTTPException

from app.schemas.rephrase import RephraseRequest, RephraseResponse
from app.services.rephrase import rephrase_answer
from app.config import settings

router = APIRouter(prefix="/rephrase", tags=["rephrase"])


@router.post("", response_model=RephraseResponse)
def rephrase(body: RephraseRequest) -> RephraseResponse:
    """
    Accept a question and an answer; return the answer rephrased in a more technical way.
    Uses the configured OpenAI chat model (OPENAI_API_KEY required).
    """
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="OpenAI API key not configured. Set OPENAI_API_KEY in .env for rephrase.",
        )
    try:
        rephrased = rephrase_answer(question=body.question, answer=body.answer)
        return RephraseResponse(rephrased_answer=rephrased)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rephrase failed: {str(e)}") from e
