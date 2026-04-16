"""SendGrid email delivery for the morning briefing.

In dry-run mode or when SENDGRID_API_KEY is missing, writes the HTML to
logs/briefing_{date}.html instead of sending.
"""
from __future__ import annotations

import logging
from pathlib import Path

from config import CONFIG

log = logging.getLogger(__name__)


def _subject(date: str, usd_rate: float | None) -> str:
    if usd_rate is None:
        return f"PI Treasury Briefing - {date}"
    return f"PI Treasury Briefing - {date} | USD/INR: {usd_rate:.4f}"


def write_html_to_disk(html: str, date: str) -> Path:
    CONFIG.logs_dir.mkdir(parents=True, exist_ok=True)
    out = CONFIG.logs_dir / f"briefing_{date}.html"
    out.write_text(html, encoding="utf-8")
    return out


def send_briefing_email(
    html: str,
    text: str,
    date: str,
    usd_rate: float | None = None,
    dry_run: bool = False,
) -> dict:
    """Send the briefing via SendGrid. Returns {success, path?, error?}."""
    preview = write_html_to_disk(html, date)
    log.info("email_service: HTML preview saved to %s", preview)

    if dry_run:
        return {"success": True, "dry_run": True, "path": str(preview)}

    if not CONFIG.sendgrid_api_key:
        log.warning("email_service: SENDGRID_API_KEY not set - skipping live send")
        return {"success": False, "error": "no_sendgrid_key", "path": str(preview)}

    if not CONFIG.to_emails:
        log.warning("email_service: TO_EMAILS empty - skipping live send")
        return {"success": False, "error": "no_recipients", "path": str(preview)}

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email, To, Content
    except ImportError as exc:
        log.error("email_service: sendgrid package not installed: %s", exc)
        return {"success": False, "error": f"import: {exc}", "path": str(preview)}

    subject = _subject(date, usd_rate)
    try:
        mail = Mail(
            from_email=Email(CONFIG.from_email, CONFIG.from_name),
            to_emails=[To(addr) for addr in CONFIG.to_emails],
            subject=subject,
            plain_text_content=Content("text/plain", text),
            html_content=Content("text/html", html),
        )
        client = SendGridAPIClient(CONFIG.sendgrid_api_key)
        response = client.send(mail)
        status = int(response.status_code)
        if 200 <= status < 300:
            log.info("email_service: sent to %d recipient(s) - HTTP %s",
                     len(CONFIG.to_emails), status)
            return {"success": True, "status": status, "path": str(preview)}
        err_body = getattr(response, "body", None)
        log.error("email_service: SendGrid HTTP %s - %s", status, err_body)
        return {"success": False, "error": f"http_{status}: {err_body}", "path": str(preview)}
    except Exception as exc:
        log.error("email_service: send failed: %s", exc)
        return {"success": False, "error": str(exc), "path": str(preview)}
