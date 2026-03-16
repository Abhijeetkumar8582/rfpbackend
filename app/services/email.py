"""SendGrid email service wrapper."""
from __future__ import annotations

import logging
from typing import Iterable

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email as SGEmail, To

from app.config import settings

logger = logging.getLogger(__name__)


def send_email(
    to_emails: Iterable[str],
    subject: str,
    plain_content: str,
    html_content: str | None = None,
    reply_to: str | None = None,
) -> bool:
    """
    Send an email via SendGrid.

    Returns True on success, False if sending fails or SendGrid is not configured.
    """
    if not (settings.sendgrid_api_key or "").strip():
        logger.warning(
            "SendGrid API key not configured (SENDGRID_API_KEY empty or missing); email not sent"
        )
        return False

    to_list = list(to_emails)
    if not to_list:
        logger.warning("send_email called with no recipients")
        return False

    from_email = SGEmail(
        email=settings.sendgrid_from_email, name=settings.sendgrid_from_name
    )
    tos = [To(email=addr) for addr in to_list]
    mail = Mail(
        from_email=from_email,
        to_emails=tos,
        subject=subject,
        plain_text_content=plain_content,
        html_content=html_content or plain_content,
    )

    if reply_to:
        mail.reply_to = SGEmail(reply_to)

    try:
        sg = SendGridAPIClient(api_key=settings.sendgrid_api_key)
        response = sg.send(mail)
        status = response.status_code or 500
        if 200 <= status < 300:
            logger.info("Email sent via SendGrid to %s (status=%s)", to_list, status)
            return True
        logger.warning(
            "SendGrid returned non-success status=%s for to=%s; body=%s",
            status,
            to_list,
            getattr(response, "body", "")[:200],
        )
        return False
    except Exception as e:
        logger.exception("SendGrid send failed to %s: %s", to_list, e)
        return False
