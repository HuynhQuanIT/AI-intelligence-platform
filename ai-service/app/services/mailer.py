"""Gửi email. MAIL_BACKEND: smtp (thật) | console (in ra log, chỉ để thử local) | memory (test)."""
import logging
import smtplib
from email.message import EmailMessage

from ..core.settings import env, env_int

logger = logging.getLogger(__name__)

# Chỉ dùng khi MAIL_BACKEND=memory (test).
OUTBOX: list[dict] = []


def send(to: str, subject: str, body: str) -> None:
    backend = env("MAIL_BACKEND", "console").lower()

    if backend == "memory":
        OUTBOX.append({"to": to, "subject": subject, "body": body})
    elif backend == "smtp":
        _send_smtp(to, subject, body)
    else:
        # Mã OTP hiện trong log: chỉ chấp nhận khi chạy thử trên máy mình.
        logger.warning("MAIL_BACKEND=console - email tới %s | %s\n%s", to, subject, body)


def _send_smtp(to: str, subject: str, body: str) -> None:
    host = env("SMTP_HOST")
    if not host:
        raise RuntimeError("MAIL_BACKEND=smtp nhưng chưa đặt SMTP_HOST")

    user = env("SMTP_USER")
    message = EmailMessage()
    message["From"] = env("MAIL_FROM") or user
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    port = env_int("SMTP_PORT", 587)
    if env("SMTP_SSL").lower() in {"1", "true", "yes"}:
        client = smtplib.SMTP_SSL(host, port, timeout=15)
    else:
        client = smtplib.SMTP(host, port, timeout=15)
        client.starttls()
    with client:
        if user:
            client.login(user, env("SMTP_PASSWORD"))
        client.send_message(message)


def send_safely(to: str, subject: str, body: str) -> None:
    """Dùng làm tác vụ nền: lỗi gửi thư chỉ ghi log, không làm hỏng response."""
    try:
        send(to, subject, body)
    except Exception:
        logger.exception("Không gửi được email tới %s", to)
