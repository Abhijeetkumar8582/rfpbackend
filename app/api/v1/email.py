"""Email API — send email via SendGrid."""
from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUserOptional
from app.schemas.email import EmailSendRequest, EmailSendResponse
from app.services.email import send_email
from app.config import settings

router = APIRouter(prefix="/email", tags=["email"])


def _require_auth(current_user: CurrentUserOptional):
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")


@router.post("/send", response_model=EmailSendResponse)
def send_email_api(
    body: EmailSendRequest,
    current_user: CurrentUserOptional,
):
    """
    Send an email via SendGrid.
    Requires authentication. Recipients, subject, and plain_content are required.
    """
    _require_auth(current_user)

    if not settings.sendgrid_api_key:
        return EmailSendResponse(
            sent=False,
            message="Email service is not configured (missing SENDGRID_API_KEY).",
        )

    to_list = [body.to] if isinstance(body.to, str) else body.to
    ok = send_email(
        to_emails=to_list,
        subject=body.subject,
        plain_content=body.plain_content,
        html_content=body.html_content,
        reply_to=body.reply_to,
    )
    return EmailSendResponse(
        sent=ok,
        message="Email sent successfully." if ok else "Failed to send email.",
    )
