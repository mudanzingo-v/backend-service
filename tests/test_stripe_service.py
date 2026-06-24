"""
Stripe service unit tests — `req-stripe-foundation-001`.

Seven acceptance scenarios, all running WITHOUT real network calls to
`api.stripe.com`. Mock-mode scenarios exercise the local-dev branch
(returns synthetic session, no SDK call). Real-mode scenarios monkey-
patch the Stripe SDK so the test suite stays hermetic.

Pin the spec contract:
- mock-mode triggered by `stripe_secret_key == ""` AND `is_local is True`
- real-mode calls `stripe.checkout.Session.create` with the documented
  `mode`/`line_items`/`success_url`/`cancel_url`/`metadata` shape
- `retrieve_checkout_session` returns EXACTLY 6 keys
- Stripe SDK errors (`StripeError`, `InvalidRequestError`) wrap into the
  app-level `StripeError` (defined in `app.core.exceptions`)
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import stripe
import stripe.error

from app.config import Settings, settings
from app.core.exceptions import StripeError
from app.services.stripe import (
    create_checkout_session,
    retrieve_checkout_session,
)

# --- Constants used across multiple scenarios ----------------------------

_AUCTION_ID = "auct_11111111-1111-1111-1111-111111111111"
_PROVIDER_ID = "prov_22222222-2222-2222-2222-222222222222"
_AMOUNT_CENTS = 12789
_CURRENCY = "mxn"
_SUCCESS_URL = "https://b2c.example.com/payment/success"
_CANCEL_URL = "https://b2c.example.com/payment/cancel"


# ---------------------------------------------------------------------------
# Service unit tests (5 scenarios)
# ---------------------------------------------------------------------------


async def test_create_checkout_session_in_mock_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Scenario: `test_create_checkout_session_in_mock_mode`

    GIVEN `settings.stripe_secret_key == ""` AND `settings.is_local is True`
    WHEN `create_checkout_session(...)` is called
    THEN the returned dict has the synthetic `cs_test_mock_<uuid>` id
         and a `localhost:3051/payment/mock?session_id=...&auction_id=...` url
         AND NO HTTP request was made to `api.stripe.com`.
    """
    # Force mock-mode flags explicitly. `is_local` is a @property derived
    # from `app_env`, so we patch the source attribute.
    monkeypatch.setattr(settings, "stripe_secret_key", "", raising=False)
    monkeypatch.setattr(settings, "app_env", "local", raising=False)

    # Tripwire: any call to the SDK create() would fail this test loudly.
    sdk_create = MagicMock()
    monkeypatch.setattr(stripe.checkout.Session, "create", sdk_create)

    result = await create_checkout_session(
        auction_id=_AUCTION_ID,
        provider_id=_PROVIDER_ID,
        amount_cents=_AMOUNT_CENTS,
        currency=_CURRENCY,
        success_url=_SUCCESS_URL,
        cancel_url=_CANCEL_URL,
    )

    # SDK must NOT have been called.
    sdk_create.assert_not_called()

    # Shape: synthetic id prefix + url targets the B2C frontend mock page.
    assert isinstance(result, dict)
    assert result["id"].startswith("cs_test_mock_"), (
        f"mock session id should be 'cs_test_mock_<uuid>'; got {result['id']!r}"
    )
    assert result["url"] == (
        f"http://localhost:3051/payment/mock"
        f"?session_id={result['id']}&auction_id={_AUCTION_ID}"
    ), f"unexpected mock url: {result['url']!r}"
    # Mock session also normalizes to the 6-key contract.
    assert result["amount_total"] == _AMOUNT_CENTS
    assert result["currency"] == _CURRENCY
    assert result["status"] == "open"
    assert result["payment_status"] == "unpaid"


async def test_create_checkout_session_real_mode_calls_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Scenario: `test_create_checkout_session_real_mode_calls_sdk`

    GIVEN `settings.stripe_secret_key == "sk_test_..."` AND `is_local is False`
    WHEN `create_checkout_session(...)` is called
    THEN `stripe.checkout.Session.create` is called once with the documented
         `mode`/`line_items`/`success_url`/`cancel_url`/`metadata` shape
         AND the returned dict matches the SDK response.
    """
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake", raising=False)
    monkeypatch.setattr(settings, "app_env", "prod", raising=False)

    sdk_session = MagicMock()
    sdk_session.id = "cs_test_real_abc123"
    sdk_session.url = "https://checkout.stripe.com/c/pay/cs_test_real_abc123"
    sdk_session.status = "open"
    sdk_session.payment_status = "unpaid"
    sdk_session.amount_total = _AMOUNT_CENTS
    sdk_session.currency = _CURRENCY
    sdk_create = MagicMock(return_value=sdk_session)
    monkeypatch.setattr(stripe.checkout.Session, "create", sdk_create)

    result = await create_checkout_session(
        auction_id=_AUCTION_ID,
        provider_id=_PROVIDER_ID,
        amount_cents=_AMOUNT_CENTS,
        currency=_CURRENCY,
        success_url=_SUCCESS_URL,
        cancel_url=_CANCEL_URL,
    )

    sdk_create.assert_called_once()
    kwargs = sdk_create.call_args.kwargs
    assert kwargs["mode"] == "payment"
    assert kwargs["success_url"] == _SUCCESS_URL
    assert kwargs["cancel_url"] == _CANCEL_URL
    assert kwargs["line_items"] == [
        {
            "price_data": {
                "currency": _CURRENCY,
                "unit_amount": _AMOUNT_CENTS,
                "product_data": {"name": f"Mobbit Auction {_AUCTION_ID}"},
            },
            "quantity": 1,
        }
    ]
    assert kwargs["metadata"] == {
        "auction_id": _AUCTION_ID,
        "provider_id": _PROVIDER_ID,
    }

    # Returned dict must match the SDK session.
    assert result == {
        "id": "cs_test_real_abc123",
        "url": "https://checkout.stripe.com/c/pay/cs_test_real_abc123",
        "status": "open",
        "payment_status": "unpaid",
        "amount_total": _AMOUNT_CENTS,
        "currency": _CURRENCY,
    }


async def test_create_checkout_session_raises_on_stripe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Scenario: `test_create_checkout_session_raises_on_stripe_error`

    GIVEN `stripe.checkout.Session.create` raises `stripe.error.StripeError`
    WHEN `create_checkout_session(...)` is called
    THEN `StripeError` (the app-level one) is raised with the original message.
    """
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake", raising=False)
    monkeypatch.setattr(settings, "app_env", "prod", raising=False)

    original_msg = "card was declined"
    sdk_create = MagicMock(
        side_effect=stripe.error.StripeError(original_msg, http_status=402)
    )
    monkeypatch.setattr(stripe.checkout.Session, "create", sdk_create)

    with pytest.raises(StripeError) as excinfo:
        await create_checkout_session(
            auction_id=_AUCTION_ID,
            provider_id=_PROVIDER_ID,
            amount_cents=_AMOUNT_CENTS,
            currency=_CURRENCY,
            success_url=_SUCCESS_URL,
            cancel_url=_CANCEL_URL,
        )
    assert str(excinfo.value) == original_msg


async def test_retrieve_checkout_session_returns_normalized_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Scenario: `test_retrieve_checkout_session_returns_normalized_dict`

    GIVEN `stripe.checkout.Session.retrieve` returns a `StripeObject`
          with `id`, `url`, `status`, `payment_status`, `amount_total`, `currency`
    WHEN `retrieve_checkout_session("cs_test_abc")` is called
    THEN the returned dict has exactly those 6 keys (and nothing else).
    """
    sdk_session = MagicMock(spec=stripe.checkout.Session)
    sdk_session.id = "cs_test_abc"
    sdk_session.url = "https://checkout.stripe.com/c/pay/cs_test_abc"
    sdk_session.status = "complete"
    sdk_session.payment_status = "paid"
    sdk_session.amount_total = 12789
    sdk_session.currency = "mxn"
    sdk_retrieve = MagicMock(return_value=sdk_session)
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", sdk_retrieve)

    result = await retrieve_checkout_session("cs_test_abc")

    sdk_retrieve.assert_called_once_with("cs_test_abc")
    assert result == {
        "id": "cs_test_abc",
        "url": "https://checkout.stripe.com/c/pay/cs_test_abc",
        "status": "complete",
        "payment_status": "paid",
        "amount_total": 12789,
        "currency": "mxn",
    }
    # Hard pin: exactly 6 keys, no leak from the SDK object.
    assert set(result.keys()) == {
        "id",
        "url",
        "status",
        "payment_status",
        "amount_total",
        "currency",
    }


async def test_retrieve_session_raises_on_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Scenario: `test_retrieve_session_raises_on_not_found`

    GIVEN `stripe.checkout.Session.retrieve` raises `InvalidRequestError`
          (session not found)
    WHEN `retrieve_checkout_session("cs_test_missing")` is called
    THEN `StripeError` is raised.
    """
    sdk_retrieve = MagicMock(
        side_effect=stripe.error.InvalidRequestError(
            message="No such checkout session: 'cs_test_missing'",
            param="session_id",
            code="resource_missing",
            http_status=404,
        )
    )
    monkeypatch.setattr(stripe.checkout.Session, "retrieve", sdk_retrieve)

    with pytest.raises(StripeError) as excinfo:
        await retrieve_checkout_session("cs_test_missing")
    assert "No such checkout session" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Configuration tests (2 scenarios)
# ---------------------------------------------------------------------------


def test_config_has_stripe_settings() -> None:
    """
    Scenario: `test_config_has_stripe_settings`

    GIVEN `app.config.Settings` is imported
    WHEN `settings.stripe_secret_key`, `stripe_publishable_key`,
         `stripe_webhook_secret`, `stripe_api_version` are accessed
    THEN each returns its documented default without raising.
    """
    # Build a fresh Settings to avoid any monkey-patched state from earlier tests.
    fresh = Settings()
    assert fresh.stripe_secret_key == ""
    assert fresh.stripe_publishable_key == ""
    assert fresh.stripe_webhook_secret == ""
    assert fresh.stripe_api_version == "2024-06-20"


def test_pyproject_has_stripe_dependency() -> None:
    """
    Scenario: `test_pyproject_has_stripe_dependency`

    GIVEN `pyproject.toml` is read
    WHEN `dependencies` are parsed
    THEN the string `"stripe>=7.0.0,<8.0.0"` appears in the list.

    Regression guard against accidental removal of the SDK pin.
    """
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with pyproject_path.open("rb") as fh:
        data = tomllib.load(fh)
    deps = data["project"]["dependencies"]
    assert "stripe>=7.0.0,<8.0.0" in deps, (
        f"stripe SDK pin missing from pyproject.toml [project.dependencies]; "
        f"found: {deps}"
    )