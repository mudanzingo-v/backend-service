"""
SMS service — sends transactional SMS via Twilio.

Mock mode (local dev without credentials): logs the message instead of
sending, matching the pattern used by Stripe and CFDI services.

Config via env vars:
- TWILIO_ACCOUNT_SID (empty → mock mode when is_local)
- TWILIO_AUTH_TOKEN
- TWILIO_FROM_NUMBER (e.g. +521234567890)
- SMS_PROVIDER_ASSIGNMENT_ENABLED (feature flag, default true)
"""
from __future__ import annotations

from app.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def _is_mock_mode() -> bool:
    """Return True when we should log instead of calling Twilio.

    Mock mode triggers when ``twilio_account_sid`` is empty AND
    ``is_local`` is True.  Local dev and the test suite depend on this
    branch — DO NOT remove.
    """
    return settings.is_local and not settings.twilio_account_sid


async def send_sms(to: str, body: str) -> bool:
    """Send an SMS via Twilio.

    In mock mode (local dev, no credentials) logs the message and returns
    True without making any HTTP call.

    Args:
        to: Recipient phone number in E.164 format (e.g. +521234567890).
        body: Message text.

    Returns:
        True on success (or mock success), False on error.
    """
    if _is_mock_mode():
        log.info(
            "sms.send.mock",
            extra={"to": to, "body": body, "from_": settings.twilio_from_number or "(mock)"},
        )
        return True

    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        log.error("sms.send.misconfigured: missing Twilio credentials")
        return False

    try:
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)

        import asyncio

        loop = asyncio.get_running_loop()

        def _send() -> None:
            client.messages.create(
                to=to,
                from_=settings.twilio_from_number,
                body=body,
            )

        await loop.run_in_executor(None, _send)
        log.info("sms.send.success", extra={"to": to})
        return True
    except Exception as exc:
        log.error("sms.send.failed", extra={"to": to, "error": str(exc)})
        return False


async def send_provider_assignment_sms(phone: str, provider_name: str) -> bool:
    """Send an SMS to a provider when a new quotation is assigned to them.

    Only sends if ``sms_provider_assignment_enabled`` is True.

    Args:
        phone: Provider's phone number (E.164).
        provider_name: Provider's display name for personalisation.

    Returns:
        True if sent (or skipped because disabled), False on error.
    """
    if not settings.sms_provider_assignment_enabled:
        log.info("sms.provider_assignment.disabled (feature flag off)")
        return True

    if not phone:
        log.warning("sms.provider_assignment.no_phone", extra={"provider_name": provider_name})
        return False

    body = (
        f"Hola {provider_name}, tienes una nueva cotización asignada en Mobbit. "
        "Ingresa a tu panel para ver los detalles y responder."
    )
    return await send_sms(phone, body)
