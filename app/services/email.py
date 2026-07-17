"""
Email service — sends transactional emails via SMTP.

Dev mode: uses MailHog (captures emails in web UI at http://localhost:8025)
Production: uses SES / SendGrid / any SMTP relay.

Config via env vars:
- SMTP_HOST (default: localhost)
- SMTP_PORT (default: 1025 for MailHog, 587 for SES)
- SMTP_USER (optional)
- SMTP_PASSWORD (optional)
- SMTP_FROM (default: noreply@mobbit.mx)
- SMTP_USE_TLS (default: False for MailHog, True for SES)
"""
from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def _smtp_config() -> dict:
    """Read SMTP config from settings."""
    return {
        "host": settings.smtp_host,
        "port": settings.smtp_port,
        "user": settings.smtp_user or None,
        "password": settings.smtp_password or None,
        "from_addr": settings.smtp_from,
        "use_tls": settings.smtp_use_tls,
    }


async def send_email(
    to: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
) -> bool:
    """Send an email via SMTP. Returns True on success, False on error."""
    cfg = _smtp_config()

    msg = MIMEMultipart("alternative")
    msg["From"] = cfg["from_addr"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain"))

    if body_html:
        msg.attach(MIMEText(body_html, "html"))

    try:
        import asyncio

        loop = asyncio.get_running_loop()

        def _send() -> None:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as server:
                if cfg["use_tls"]:
                    server.starttls()
                if cfg["user"] and cfg["password"]:
                    server.login(cfg["user"], cfg["password"])
                server.send_message(msg)

        await loop.run_in_executor(None, _send)
        log.info("Email sent: to=%s subject=%s", to, subject)
        return True
    except Exception as exc:
        log.error("Email send failed: to=%s error=%s", to, exc)
        return False


async def send_verification_email(to: str, verification_url: str) -> bool:
    """Send the email verification magic link."""
    subject = "Verifica tu email — Mobbit"
    body_text = f"""Hola,

Gracias por registrarte en Mobbit. Para activar tu cuenta, haz clic en este enlace:

{verification_url}

Este enlace expira en 24 horas.

Si no solicitaste este registro, ignora este mensaje.

— Mobbit
"""
    body_html = f"""<html><body>
<p>Gracias por registrarte en <strong>Mobbit</strong>.</p>
<p>Para activar tu cuenta, haz clic en el siguiente botón:</p>
<p><a href="{verification_url}" style="display:inline-block;padding:12px 24px;background:#0052CC;color:#fff;text-decoration:none;border-radius:6px;">
    Verificar Email
</a></p>
<p>O copia este enlace en tu navegador:</p>
<p><code>{verification_url}</code></p>
<p><em>Este enlace expira en 24 horas.</em></p>
</body></html>"""

    return await send_email(to, subject, body_text, body_html)
