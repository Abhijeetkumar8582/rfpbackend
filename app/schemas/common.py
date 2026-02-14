"""Common Pydantic schemas."""
from pydantic import BaseModel


class Message(BaseModel):
    message: str


class IDResponse(BaseModel):
    id: int
