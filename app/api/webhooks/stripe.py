"""
Stripe webhook — receives events from Stripe, verifies the signature,
and updates DB state for the matching CheckoutSession + Payment + Auction.

Endpoint: ``POST /webhooks/payments/stripe``

Subscribed events (per design §OQ1):

- ``checkout.session.completed`` — primary trigger. Marks
  ``Payment.state = "PAID"`` and transitions ``Auction.state`` from
  ``SELECTED → ACCEPTED``. Idempotent: re-firing the same event id
  is a no-op (see §OQ2 ``last_event_id``).
- ``payment_intent.succeeded`` — backup for synchronous card payments
  that fire ``payment_intent.succeeded`` before
  ``checkout.session.completed``. Same effect as
  ``checkout.session.completed``.
- ``payment_intent.payment_failed`` — marks ``Payment.state = "FAILED"``.
  Does NOT touch ``Auction.state`` (the auction stays ``SELECTED``; admin
  can manually cancel later).

Other event types (``charge.refunded``, ``customer.created``, etc.)
return 200 with ``{"received": true}`` and a log line — never mutate
the DB. Refund handling is deferred per design §OQ3.

The MP webhook at ``app/api/webhooks/mercadopago.py`` is now dead
(replaced in ``app/main.py``) and will be deleted in PR4.

Signature verification
----------------------

Uses ``stripe.Webhook.construct_event`` from the Stripe Python SDK.
The ``STRIPE_WEBHOOK_SECRET`` is read from ``settings.stripe_webhook_secret``
at request time (so a dev-server env reload picks up a rotated secret
without a process restart). On invalid signature OR missing header we
return 400 with ``{"detail": "Invalid signature"}`` and **do not mutate
the DB** — Stripe will retry on non-2xx until it gets a 2xx.
"""
from __future__ import annotations

from typing import Any

import stripe
import stripe.error
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.models import Auction, CheckoutSession, Payment

log = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# Public constants for test introspection (test code reads these).
WEBHOOK_PATH = "/payments/stripe"


@router.post(WEBHOOK_PATH)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Stripe webhook entrypoint.

    Returns:

    - 200 ``{"received": true}`` on successful processing (any event
      type, including unknown ones — Stripe treats that as success and
      stops retrying).
    - 400 ``{"detail": "..."}`` on missing or invalid signature.
    """
    body = await request.body()

    if not stripe_signature:
        log.warning("Stripe webhook called without Stripe-Signature header")
        return JSONResponse(
            status_code=400,
            content={"detail": "Missing Stripe-Signature header"},
        )

    try:
        event = stripe.Webhook.construct_event(
            body,
            stripe_signature,
            settings.stripe_webhook_secret,
        )
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        log.warning("Stripe webhook signature verification failed: %s", exc)
        return JSONResponse(
            status_code=400,
            content={"detail": "Invalid signature"},
        )

    log.info(
        "stripe.webhook.received",
        extra={"event_id": event.id, "event_type": event.type},
    )

    if event.type == "checkout.session.completed":
        await _on_checkout_completed(db, event)
    elif event.type == "payment_intent.succeeded":
        await _on_payment_succeeded(db, event)
    elif event.type == "payment_intent.payment_failed":
        await _on_payment_failed(db, event)
    else:
        # Unknown / not-subscribed event. We acknowledge so Stripe
        # doesn't retry, but we don't touch the DB. Refund handling
        # (`charge.refunded`) lands in a future change.
        log.info(
            "stripe.webhook.ignored",
            extra={
                "event_id": event.id,
                "event_type": event.type,
                "reason": "not subscribed",
            },
        )

    await db.commit()
    return JSONResponse(content={"received": True})


# ---------------------------------------------------------------------------
# Dispatch handlers
# ---------------------------------------------------------------------------


async def _lookup_session_by_stripe_id(
    db: AsyncSession, stripe_session_id: str | None
) -> CheckoutSession | None:
    """Find a CheckoutSession by ``stripe_session_id`` (NOT the local PK).

    Returns ``None`` if the session is not in the DB (e.g. the B2C flow
    never finished ``select_auction``). Callers should treat that as a
    log-and-skip case.
    """
    if not stripe_session_id:
        return None
    stmt = select(CheckoutSession).where(
        CheckoutSession.stripe_session_id == stripe_session_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _lookup_payment_for_session(
    db: AsyncSession, stripe_session_id: str | None
) -> Payment | None:
    """Find the Payment row that references this Stripe checkout session."""
    if not stripe_session_id:
        return None
    stmt = select(Payment).where(
        Payment.stripe_checkout_session_id == stripe_session_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _mark_session_and_payment_paid(
    db: AsyncSession,
    session: CheckoutSession,
    payment: Payment | None,
    event_id: str,
) -> bool:
    """Idempotently mark a CheckoutSession + Payment as paid and ACCEPT
    the auction. Returns True if a state transition happened, False
    if the event was a duplicate or no-op.
    """
    # Idempotency: same event id already processed.
    if session.last_event_id == event_id:
        log.info(
            "stripe.webhook.duplicate_event",
            extra={"event_id": event_id, "session_id": session.stripe_session_id},
        )
        return False

    session.last_event_id = event_id
    session.payment_status = "paid"

    if payment is None:
        log.warning(
            "stripe.webhook.no_payment_for_session",
            extra={"stripe_session_id": session.stripe_session_id},
        )
        return False

    # Payment-level idempotency: if already PAID, skip the auction transition
    # (the previous webhook already ACCEPTed the auction).
    if payment.state == "PAID":
        log.info(
            "stripe.webhook.payment_already_paid",
            extra={
                "event_id": event_id,
                "payment_id": payment.id,
            },
        )
        return False

    payment.state = "PAID"
    payment.stripe_payment_status = "succeeded"

    # Auction transition: SELECTED → ACCEPTED. Only happens once.
    auction = await db.get(Auction, session.auction_id)
    if auction is not None and auction.state == "SELECTED":
        auction.state = "ACCEPTED"
        log.info(
            "stripe.webhook.auction_accepted",
            extra={
                "event_id": event_id,
                "auction_id": auction.id,
            },
        )
    return True


async def _on_checkout_completed(db: AsyncSession, event: Any) -> None:
    """``checkout.session.completed`` handler.

    Fires when the customer finishes the Stripe-hosted checkout. The
    ``data.object.id`` is the Stripe session id (``cs_test_...``).
    """
    stripe_session_id: str | None = event.data.object.get("id")
    session = await _lookup_session_by_stripe_id(db, stripe_session_id)
    if session is None:
        log.warning(
            "stripe.webhook.completed.unknown_session",
            extra={"stripe_session_id": stripe_session_id},
        )
        return
    payment = await _lookup_payment_for_session(db, stripe_session_id)
    await _mark_session_and_payment_paid(db, session, payment, event.id)


async def _on_payment_succeeded(db: AsyncSession, event: Any) -> None:
    """``payment_intent.succeeded`` handler.

    Fires for synchronous card payments, sometimes before
    ``checkout.session.completed``. The ``data.object`` is a
    PaymentIntent; the parent checkout session id is in
    ``data.object.checkout_session``.
    """
    pi = event.data.object
    stripe_session_id: str | None = (
        pi.get("checkout_session") if isinstance(pi, dict) else None
    ) or (pi.get("id") if isinstance(pi, dict) else None)
    session = await _lookup_session_by_stripe_id(db, stripe_session_id)
    if session is None:
        log.warning(
            "stripe.webhook.intent_succeeded.unknown_session",
            extra={"stripe_session_id": stripe_session_id},
        )
        return
    payment = await _lookup_payment_for_session(db, stripe_session_id)
    await _mark_session_and_payment_paid(db, session, payment, event.id)


async def _on_payment_failed(db: AsyncSession, event: Any) -> None:
    """``payment_intent.payment_failed`` handler.

    Marks the Payment FAILED. Does NOT touch the Auction state — it
    stays SELECTED so admin can manually cancel (or the client can retry).
    Idempotent on duplicate event id.
    """
    pi = event.data.object
    stripe_session_id: str | None = (
        pi.get("checkout_session") if isinstance(pi, dict) else None
    ) or (pi.get("id") if isinstance(pi, dict) else None)
    session = await _lookup_session_by_stripe_id(db, stripe_session_id)
    if session is None:
        log.warning(
            "stripe.webhook.intent_failed.unknown_session",
            extra={"stripe_session_id": stripe_session_id},
        )
        return

    if session.last_event_id == event.id:
        log.info(
            "stripe.webhook.duplicate_event",
            extra={"event_id": event.id, "session_id": session.stripe_session_id},
        )
        return

    session.last_event_id = event.id
    payment = await _lookup_payment_for_session(db, stripe_session_id)
    if payment is not None and payment.state != "FAILED":
        payment.state = "FAILED"
        payment.stripe_payment_status = "failed"
        log.info(
            "stripe.webhook.payment_failed",
            extra={
                "event_id": event.id,
                "payment_id": payment.id,
            },
        )
