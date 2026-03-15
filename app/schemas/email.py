"""Email API schemas."""
from pydantic import BaseModel, EmailStr, Field


class EmailSendRequest(BaseModel):
    """Request body for sending an email."""

    to: EmailStr | list[EmailStr] = Field(..., description="Recipient email(s)")
    subject: str = Field(..., min_length=1, max_length=998, description="Email subject")
    plain_content: str = Field(..., min_length=1, description="Plain text body")
    html_content: str | None = Field(None, description="Optional HTML body")
    reply_to: EmailStr | None = Field(None, description="Optional reply-to address")


class EmailSendResponse(BaseModel):
    """Response after sending an email."""

    sent: bool = Field(..., description="Whether the email was sent successfully")
    message: str = Field(..., description="Status message")
