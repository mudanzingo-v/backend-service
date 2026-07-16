"""
SMS service tests — mock mode, feature flag, missing phone.

All tests run in mock mode (no Twilio credentials needed) because the
test conftest sets ``APP_ENV=local`` and ``TWILIO_ACCOUNT_SID`` is empty.
"""
from __future__ import annotations

import pytest

from app.services import sms as sms_svc


# =============================================================================
# send_sms (low-level)
# =============================================================================


async def test_send_sms_mock_mode_logs_and_returns_true() -> None:
    """In mock mode, send_sms returns True without calling Twilio."""
    result = await sms_svc.send_sms("+521234567890", "Test message")
    assert result is True


async def test_send_sms_empty_recipient() -> None:
    """send_sms with an empty string still returns True in mock mode."""
    result = await sms_svc.send_sms("", "body")
    assert result is True


async def test_send_sms_special_chars() -> None:
    """Special characters in the body don't break mock mode."""
    result = await sms_svc.send_sms(
        "+521234567890",
        "Hola José, tienes una cita mañana a las 10:30 — Mobbit 🚛",
    )
    assert result is True


# =============================================================================
# send_provider_assignment_sms (high-level)
# =============================================================================


async def test_provider_assignment_sends_with_phone() -> None:
    """When provider has a phone and feature flag is on, SMS is sent."""
    result = await sms_svc.send_provider_assignment_sms(
        phone="+521234567890",
        provider_name="Juan Pérez",
    )
    assert result is True


async def test_provider_assignment_no_phone_returns_false() -> None:
    """When provider has no phone, returns False (can't send)."""
    result = await sms_svc.send_provider_assignment_sms(
        phone="",
        provider_name="Juan Pérez",
    )
    assert result is False


async def test_provider_assignment_disabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """When sms_provider_assignment_enabled is False, skips send."""
    from app.config import settings
    monkeypatch.setattr(settings, "sms_provider_assignment_enabled", False)
    result = await sms_svc.send_provider_assignment_sms(
        phone="+521234567890",
        provider_name="Juan Pérez",
    )
    assert result is True  # skipped gracefully, not an error
