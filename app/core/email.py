import logging

import resend
from fastapi.concurrency import run_in_threadpool

from app.core.config import settings

logger = logging.getLogger(__name__)

resend.api_key = settings.RESEND_API_KEY


async def send_email(to: str, subject: str, body: str) -> None:
    payload = {
        "from": f"Enwis <{settings.MAIL_FROM}>",
        "to": [to],
        "subject": subject,
        "html": body,
    }
    try:
        response = await run_in_threadpool(resend.Emails.send, payload)
        logger.info("Email sent to %s | id=%s", to, getattr(response, "id", "?"))
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to, exc)
        raise


# Placeholder — email_templates module will be added later
def get_reset_email_html(link: str) -> str:
    return f"<a href='{link}'>Reset password</a>"
