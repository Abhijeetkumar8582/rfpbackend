"""Email service — SendGrid integration for sending transactional emails."""
import logging
from typing import List

from app.config import settings

logger = logging.getLogger(__name__)


def send_email(
    to_emails: str | List[str],
    subject: str,
    plain_content: str,
    html_content: str | None = None,
    from_email: str | None = None,
    from_name: str | None = None,
    reply_to: str | None = None,
) -> bool:
    """
    Send an email via SendGrid.
    Returns True on success, False if SendGrid is not configured or on error.
    """
    if not settings.sendgrid_api_key:
        logger.warning("SendGrid API key not configured; email not sent")
        return False

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email, To, Content

        to_list = [to_emails] if isinstance(to_emails, str) else to_emails
        from_addr = Email(
            email=from_email or settings.sendgrid_from_email,
            name=from_name or settings.sendgrid_from_name,
        )
        to_addrs = [To(email=e) for e in to_list]
        plain = Content("text/plain", plain_content)
        message = Mail(
            from_email=from_addr,
            to_emails=to_addrs,
            subject=subject,
            plain_text_content=plain,
        )
        if html_content:
            message.add_content(Content("text/html", html_content))
        if reply_to:
            message.reply_to = Email(reply_to)

        sg = SendGridAPIClient(settings.sendgrid_api_key)
        sg.send(message)
        logger.info("Email sent via SendGrid to %s", to_list)
        return True
    except Exception as e:
        logger.exception("SendGrid send failed: %s", e)
        return False
