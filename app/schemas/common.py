"""Common Pydantic schemas."""
from pydantic import BaseModel


class Message(BaseModel):
    message: str


class IDResponse(BaseModel):
    id: int | str  # project id is str (PROJ-YYYY-NNN), document id is int
