"""
Email service tests — send email + verification email.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.email import send_email, send_verification_email


async def test_send_email_success() -> None:
    """`send_email` returns True when SMTP succeeds."""
    import app.services.email as email_mod

    mock_server = patch.object(email_mod.smtplib, "SMTP").start()
    mock_instance = mock_server.return_value
    mock_instance.__enter__.return_value = mock_instance

    result = await send_email(
        to="test@example.com",
        subject="Test",
        body_text="Hello",
    )

    assert result is True
    mock_server.assert_called_once_with("localhost", 1025, timeout=10)
    mock_instance.send_message.assert_called_once()
    mock_instance.__exit__.assert_called_once()


async def test_send_email_failure_returns_false() -> None:
    """`send_email` returns False when SMTP fails."""
    import app.services.email as email_mod

    patch.object(email_mod.smtplib, "SMTP", side_effect=ConnectionRefusedError()).start()

    result = await send_email(
        to="test@example.com",
        subject="Test",
        body_text="Hello",
    )
    assert result is False


async def test_send_verification_email() -> None:
    """`send_verification_email` sends with correct to/from/subject."""
    import app.services.email as email_mod

    mock_server = patch.object(email_mod.smtplib, "SMTP").start()
    mock_instance = mock_server.return_value
    mock_instance.__enter__.return_value = mock_instance

    result = await send_verification_email(
        to="provider@example.com",
        verification_url="https://mobbit.mx/verify?token=abc123",
    )

    assert result is True
    msg = mock_instance.send_message.call_args[0][0]
    assert msg["To"] == "provider@example.com"
    assert msg["From"] == "noreply@mobbit.mx"
    assert "Verifica tu email" in msg["Subject"]
