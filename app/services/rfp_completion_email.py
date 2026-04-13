"""RFP completion notification — HTML email + Excel attachment when all answers are generated."""
from __future__ import annotations

import html
import io
import logging
import re
from typing import TYPE_CHECKING

from openpyxl import Workbook

from app.config import settings
from app.services.email import send_email

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def build_qa_excel_bytes(questions: list, raw_answers: list[str]) -> bytes:
    """Build an .xlsx with columns Question and Answer."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Q_and_A"
    ws.append(["Question", "Answer"])
    n = len(questions)
    for i in range(n):
        q = str(questions[i] if i < len(questions) else "") or ""
        a = str(raw_answers[i] if i < len(raw_answers) else "") or ""
        ws.append([q, a])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def safe_attachment_filename(name: str, rfpid: str) -> str:
    base = re.sub(r'[<>:"/\\|?*\u0000-\u001f]', "_", (name or "RFP").strip())[:100] or "RFP"
    return f"{base}_{rfpid[:12]}.xlsx"


def _frontend_base() -> str:
    b = (settings.frontend_base_url or "").strip().rstrip("/")
    if not b or "yourdomain.com" in b.lower():
        return "http://localhost:3000"
    return b


def render_completion_html(
    *,
    user_name: str,
    rfp_title: str,
    accuracy_display: str,
    answered: int,
    unanswered: int,
    product_name: str,
    view_url: str,
) -> str:
    """Production-style HTML email (table layout, inline CSS)."""
    name_e = html.escape(user_name or "there")
    title_e = html.escape(rfp_title or "Your RFP")
    prod_e = html.escape(product_name or "RFP Platform")
    acc_e = html.escape(accuracy_display)
    view_e = html.escape(view_url, quote=True)
    preheader = f"Your RFP “{rfp_title or 'request'}” is complete — accuracy {accuracy_display}, {unanswered} unanswered."

    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <title>{prod_e} — RFP ready</title>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">{html.escape(preheader)}</div>
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color:#f1f5f9;padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" style="max-width:600px;width:100%;background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 10px 40px rgba(15,23,42,0.08);">
          <tr>
            <td style="background:linear-gradient(135deg,#ec540e 0%,#c42a0c 50%,#9a3412 100%);padding:28px 32px;text-align:left;">
              <p style="margin:0 0 8px 0;font-size:11px;font-weight:600;letter-spacing:0.12em;text-transform:uppercase;color:rgba(255,255,255,0.85);">{prod_e}</p>
              <h1 style="margin:0;font-size:24px;line-height:1.25;font-weight:700;color:#ffffff;">Your RFP is ready</h1>
              <p style="margin:12px 0 0 0;font-size:15px;line-height:1.5;color:rgba(255,255,255,0.92);">Hi {name_e}, we&apos;ve finished generating answers for your request.</p>
            </td>
          </tr>
          <tr>
            <td style="padding:28px 32px 8px 32px;">
              <p style="margin:0 0 8px 0;font-size:14px;color:#64748b;">Document</p>
              <p style="margin:0;font-size:18px;font-weight:600;color:#0f172a;line-height:1.35;">{title_e}</p>
            </td>
          </tr>
          <tr>
            <td style="padding:8px 32px 24px 32px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:separate;border-spacing:12px 0;">
                <tr>
                  <td style="width:33%;vertical-align:top;background:#eff6ff;border-radius:10px;padding:16px;border:1px solid #bfdbfe;">
                    <p style="margin:0 0 6px 0;font-size:11px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;color:#1d4ed8;">Avg. accuracy</p>
                    <p style="margin:0;font-size:26px;font-weight:700;color:#1e3a8a;line-height:1;">{acc_e}</p>
                  </td>
                  <td style="width:33%;vertical-align:top;background:#f0fdf4;border-radius:10px;padding:16px;border:1px solid #bbf7d0;">
                    <p style="margin:0 0 6px 0;font-size:11px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;color:#15803d;">Answered</p>
                    <p style="margin:0;font-size:26px;font-weight:700;color:#14532d;line-height:1;">{answered}</p>
                  </td>
                  <td style="width:33%;vertical-align:top;background:#fef2f2;border-radius:10px;padding:16px;border:1px solid #fecaca;">
                    <p style="margin:0 0 6px 0;font-size:11px;font-weight:600;letter-spacing:0.06em;text-transform:uppercase;color:#b91c1c;">Unanswered</p>
                    <p style="margin:0;font-size:26px;font-weight:700;color:#991b1b;line-height:1;">{unanswered}</p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 28px 32px;">
              <p style="margin:0;font-size:14px;line-height:1.65;color:#475569;">
                A detailed <strong style="color:#0f172a;">Excel workbook</strong> (Question &amp; Answer) is attached to this message. Open it in Microsoft Excel or Google Sheets to review or share with your team.
              </p>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 32px 32px;text-align:center;">
              <a href="{view_e}" style="display:inline-block;padding:14px 28px;background:linear-gradient(135deg,#6366f1 0%,#4f46e5 100%);color:#ffffff !important;font-size:15px;font-weight:600;text-decoration:none;border-radius:8px;box-shadow:0 4px 14px rgba(79,70,229,0.35);">View in {prod_e}</a>
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px;background-color:#f8fafc;border-top:1px solid #e2e8f0;">
              <p style="margin:0 0 6px 0;font-size:12px;color:#94a3b8;line-height:1.5;">This is an automated message from {prod_e}. Please do not reply unless you need help — contact your workspace administrator.</p>
              <p style="margin:0;font-size:11px;color:#cbd5e1;">© {prod_e}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def render_completion_plain(
    *,
    user_name: str,
    rfp_title: str,
    accuracy_display: str,
    answered: int,
    unanswered: int,
    product_name: str,
    view_url: str,
) -> str:
    return (
        f"Hi {user_name or 'there'},\n\n"
        f"We've completed generating answers for your RFP request.\n\n"
        f"Document: {rfp_title or 'Your RFP'}\n"
        f"Average answer accuracy: {accuracy_display}\n"
        f"Answered: {answered}\n"
        f"Unanswered: {unanswered}\n\n"
        f"A Question & Answer Excel file is attached.\n\n"
        f"Open in the app: {view_url}\n\n"
        f"— {product_name or 'RFP Platform'}\n"
    )


def send_rfp_completion_notification(
    *,
    to_email: str,
    user_name: str,
    rfp_title: str,
    rfpid: str,
    accuracy_pct: int | None,
    answered: int,
    unanswered: int,
    excel_bytes: bytes,
) -> None:
    """
    Send completion email with metrics and Excel attachment.
    Logs and returns quietly if SendGrid is not configured or send fails.
    """
    product = (settings.product_name or "RFP Platform").strip() or "RFP Platform"
    base = _frontend_base()
    view_url = f"{base}/upload-rfp"

    if accuracy_pct is not None:
        accuracy_display = f"{accuracy_pct}%"
    else:
        accuracy_display = "—"

    title_short = (rfp_title or "request").strip() or "request"
    subject = f'{product} — Your RFP "{title_short}" is complete'
    html_body = render_completion_html(
        user_name=user_name,
        rfp_title=rfp_title,
        accuracy_display=accuracy_display,
        answered=answered,
        unanswered=unanswered,
        product_name=product,
        view_url=view_url,
    )
    plain = render_completion_plain(
        user_name=user_name,
        rfp_title=rfp_title,
        accuracy_display=accuracy_display,
        answered=answered,
        unanswered=unanswered,
        product_name=product,
        view_url=view_url,
    )
    fname = safe_attachment_filename(rfp_title, rfpid)
    attach_kw: dict = {}
    if excel_bytes:
        attach_kw["attachments"] = [(excel_bytes, fname, _EXCEL_MIME)]

    ok = send_email(
        to_emails=[to_email],
        subject=subject,
        plain_content=plain,
        html_content=html_body,
        **attach_kw,
    )
    if ok:
        logger.info("RFP completion email sent to %s for rfpid=%s", to_email, rfpid)
    else:
        logger.warning("RFP completion email not sent (SendGrid or error) for rfpid=%s", rfpid)
