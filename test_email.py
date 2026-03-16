"""
Test script to send an email to abhijeet122kumar@gmail.com via SendGrid.
Run from backend directory: python test_email.py
"""
import sys
from pathlib import Path

# Ensure backend root is on path so app.config and app.services load correctly
_backend_root = Path(__file__).resolve().parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from app.services.email import send_email

TO_EMAIL = "abhijeet122kumar@gmail.com"
SUBJECT = "Test email from RFP backend"
PLAIN = "This is a test email sent from the RFP backend (SendGrid)."
HTML = """
<p>This is a <strong>test email</strong> sent from the RFP backend via SendGrid.</p>
<p>If you received this, email is configured correctly.</p>
"""


def main() -> None:
    ok = send_email(
        to_emails=[TO_EMAIL],
        subject=SUBJECT,
        plain_content=PLAIN,
        html_content=HTML,
    )
    if ok:
        print(f"Email sent successfully to {TO_EMAIL}")
    else:
        print("Failed to send email. Check SENDGRID_API_KEY and SENDGRID_FROM_EMAIL in .env")
        sys.exit(1)


if __name__ == "__main__":
    main()
