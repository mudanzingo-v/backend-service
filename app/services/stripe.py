"""
Stripe service — Checkout Sessions for Mobbit auctions.

Token read from env (`STRIPE_SECRET_KEY`), not from code. Mock mode
(empty `stripe_secret_key` AND `is_local=True`) returns a synthetic
Checkout Session dict without making any HTTP call to `api.stripe.com`,
so local dev and CI never hit Stripe's API. Real mode delegates to
`stripe.checkout.Session.create` / `retrieve` from the Stripe Python SDK.

Mirrors the public surface of the prior `app/services/mercadopago.py`
(create_preference / retrieve_preference analogue) but with Stripe-
neutral semantics. PR2 will swap `select_auction` to use this module
instead of the MP service.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import stripe
import stripe.error

from app.config import settings
from app.core.exceptions import StripeError
from app.core.logging import get_logger

log = get_logger(__name__)


def _is_mock_mode() -> bool:
    """Return True when we should synthesize the session instead of calling Stripe.

    Mock mode contract (pinned by `req-stripe-foundation-001 §"Pinning contract"`):
    triggered when `stripe_secret_key == ""` AND `is_local is True`. Local
    development AND the test suite depend on this branch — DO NOT remove.
    """
    return settings.is_local and not settings.stripe_secret_key


def _mock_session(*, auction_id: str, amount_cents: int, currency: str) -> dict[str, Any]:
    """Synthesize a Checkout Session dict for local dev / CI.

    The `id` uses the `cs_test_mock_<uuid>` prefix so test assertions can
    distinguish it from a real Stripe id (`cs_test_...`). The `url` points
    at the B2C frontend's mock-mode page; PR5 wires the frontend to
    recognize this URL.
    """
    session_id = f"cs_test_mock_{uuid.uuid4().hex}"
    url = (
        f"{settings.b2c_frontend_url}/payment/mock"
        f"?session_id={session_id}&auction_id={auction_id}"
    )
    return {
        "id": session_id,
        "url": url,
        "status": "open",
        "payment_status": "unpaid",
        "amount_total": amount_cents,
        "currency": currency,
    }


async def create_checkout_session(
    *,
    auction_id: str,
    provider_id: str,
    amount_cents: int,
    currency: str,
    success_url: str,
    cancel_url: str,
    customer_email: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a Stripe Checkout Session for the given auction.

    In mock mode (`is_local=True` AND `stripe_secret_key=""`) returns a
    synthetic session dict and makes NO HTTP call to `api.stripe.com`.
    Otherwise delegates to `stripe.checkout.Session.create`, wrapping any
    `stripe.error.StripeError` / `InvalidRequestError` into the app-level
    `StripeError` (HTTP 502 via the exception handler).

    Returns a dict with the standard Checkout Session fields
    (`id`, `url`, `status`, `payment_status`, `amount_total`, `currency`).
    """
    if _is_mock_mode():
        log.info(
            "stripe.create_checkout_session.mock",
            extra={"auction_id": auction_id, "amount_cents": amount_cents},
        )
        return _mock_session(
            auction_id=auction_id, amount_cents=amount_cents, currency=currency
        )

    params: dict[str, Any] = {
        "mode": "payment",
        "line_items": [
            {
                "price_data": {
                    "currency": currency,
                    "unit_amount": amount_cents,
                    "product_data": {"name": f"Mobbit Auction {auction_id}"},
                },
                "quantity": 1,
            }
        ],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": {"auction_id": auction_id, "provider_id": provider_id},
    }
    if customer_email is not None:
        params["customer_email"] = customer_email
    if metadata:
        # Merge caller-supplied metadata under our two reserved keys.
        params["metadata"].update(metadata)

    try:
        # Stripe SDK 7.x exposes a sync Session.create; offload to a thread
        # so we don't block the event loop on the HTTP round-trip.
        session = await asyncio.to_thread(stripe.checkout.Session.create, **params)
    except (stripe.error.StripeError, stripe.error.InvalidRequestError) as exc:
        log.error(
            "stripe.create_checkout_session.error",
            extra={"auction_id": auction_id, "stripe_error": str(exc)},
        )
        raise StripeError(str(exc)) from exc

    # The SDK returns a StripeObject (dict-like); normalize to a plain dict.
    return {
        "id": session.id,
        "url": session.url,
        "status": session.status,
        "payment_status": session.payment_status,
        "amount_total": session.amount_total,
        "currency": session.currency,
    }


async def retrieve_checkout_session(session_id: str) -> dict[str, Any]:
    """Retrieve a Checkout Session by id and return a normalized 6-key dict.

    The Stripe SDK returns a `StripeObject` with many fields. Per
    `req-stripe-foundation-001 §"test_retrieve_checkout_session_returns_normalized_dict"`,
    we project to exactly the 6 keys the rest of the app cares about:
    `id`, `url`, `status`, `payment_status`, `amount_total`, `currency`.

    Mock mode is NOT supported for retrieval: in dev, callers should
    pass the synthetic `cs_test_mock_<uuid>` id through to the B2C
    frontend (PR5) rather than round-tripping through this service.
    Stripe errors (including `InvalidRequestError` for not-found) are
    wrapped in the app-level `StripeError`.
    """
    try:
        session = await asyncio.to_thread(stripe.checkout.Session.retrieve, session_id)
    except (stripe.error.StripeError, stripe.error.InvalidRequestError) as exc:
        log.error(
            "stripe.retrieve_checkout_session.error",
            extra={"session_id": session_id, "stripe_error": str(exc)},
        )
        raise StripeError(str(exc)) from exc

    return {
        "id": session.id,
        "url": session.url,
        "status": session.status,
        "payment_status": session.payment_status,
        "amount_total": session.amount_total,
        "currency": session.currency,
    }