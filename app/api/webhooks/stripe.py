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
from app.models import Auction, CheckoutSession, Payment, Quotation
from app.services import invoice as invoice_svc
from app.services import refund as refund_svc
from app.services.quotation import transition_quotation
from app.services.payment_states import PAY_PAID, PAY_FAILED
from app.services.auction import STATE_SELECTED, STATE_ACCEPTED
from app.services.quotation import ST_BIDDING

log = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


WEBHOOK_PATH = "/payments/stripe"


async def _try_auto_stamp_cfdi(db: AsyncSession, payment_id: str | None) -> None:
    """After a payment goes PAID, try to auto-create and stamp the CFDI."""
    if payment_id is None:
        return
    try:
        invoice = await invoice_svc.auto_stamp_on_payment(db, payment_id)
        if invoice:
            log.info(
                "cfdi.auto_stamped",
                extra={
                    "payment_id": payment_id,
                    "invoice_id": invoice.id,
                    "status": invoice.status,
                },
            )
    except Exception as exc:
        log.warning(
            "cfdi.auto_stamp_failed",
            extra={"payment_id": payment_id, "error": str(exc)},
        )


@router.post(WEBHOOK_PATH)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
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
        payment_id = await _on_checkout_completed(db, event)
        await _try_auto_stamp_cfdi(db, payment_id)
    elif event.type == "payment_intent.succeeded":
        payment_id = await _on_payment_succeeded(db, event)
        await _try_auto_stamp_cfdi(db, payment_id)
    elif event.type == "payment_intent.payment_failed":
        await _on_payment_failed(db, event)
    elif event.type == "charge.refunded":
        await _on_charge_refunded(db, event)
    else:
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


async def _lookup_session_by_stripe_id(
    db: AsyncSession, stripe_session_id: str | None
) -> CheckoutSession | None:
    if not stripe_session_id:
        return None
    stmt = select(CheckoutSession).where(
        CheckoutSession.stripe_session_id == stripe_session_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _lookup_payment_for_session(
    db: AsyncSession, stripe_session_id: str | None
) -> Payment | None:
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

    if payment.state == PAY_PAID:
        log.info(
            "stripe.webhook.payment_already_paid",
            extra={"event_id": event_id, "payment_id": payment.id},
        )
        return False

    payment.state = PAY_PAID
    payment.stripe_payment_status = "succeeded"

    auction = await db.get(Auction, session.auction_id)
    if auction is not None and auction.state == STATE_SELECTED:
        auction.state = STATE_ACCEPTED
        log.info(
            "stripe.webhook.auction_accepted",
            extra={"event_id": event_id, "auction_id": auction.id},
        )
        # Reject all other PENDING auctions for this quotation
        stmt = select(Auction).where(
            Auction.quotation_id == auction.quotation_id,
            Auction.state == "PENDING",
            Auction.id != auction.id,
        )
        other_auctions = (await db.execute(stmt)).scalars().all()
        for other in other_auctions:
            other.state = "REJECTED"
            log.info(
                "stripe.webhook.other_auction_rejected",
                extra={"auction_id": other.id, "quotation_id": auction.quotation_id},
            )
        # Transition quotation from BIDDING to AWARDED
        quotation = await db.get(Quotation, auction.quotation_id)
        if quotation and quotation.state == ST_BIDDING:
            await transition_quotation(db, quotation.id, "AWARDED")
    return True


async def _on_checkout_completed(db: AsyncSession, event: Any) -> str | None:
    """Handler for checkout.session.completed. Returns payment_id if paid."""
    stripe_session_id: str | None = event.data.object.get("id")
    session = await _lookup_session_by_stripe_id(db, stripe_session_id)
    if session is None:
        log.warning(
            "stripe.webhook.completed.unknown_session",
            extra={"stripe_session_id": stripe_session_id},
        )
        return None
    payment = await _lookup_payment_for_session(db, stripe_session_id)
    await _mark_session_and_payment_paid(db, session, payment, event.id)
    return payment.id if payment else None


async def _on_payment_succeeded(db: AsyncSession, event: Any) -> str | None:
    """Handler for payment_intent.succeeded. Returns payment_id if paid."""
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
        return None
    payment = await _lookup_payment_for_session(db, stripe_session_id)
    await _mark_session_and_payment_paid(db, session, payment, event.id)
    return payment.id if payment else None


async def _on_payment_failed(db: AsyncSession, event: Any) -> None:
    """Handler for payment_intent.payment_failed."""
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
    if payment is not None and payment.state != PAY_FAILED:
        payment.state = PAY_FAILED
        payment.stripe_payment_status = "failed"
        log.info(
            "stripe.webhook.payment_failed",
            extra={"event_id": event.id, "payment_id": payment.id},
        )


async def _on_charge_refunded(db: AsyncSession, event: Any) -> None:
    """Handler for ``charge.refunded`` events."""
    charge = event.data.object
    payment_intent_id: str | None = charge.get("payment_intent") if isinstance(charge, dict) else None
    refund_status: str | None = charge.get("status") if isinstance(charge, dict) else None

    if not payment_intent_id:
        log.warning("refund.webhook.missing_payment_intent", extra={"event_id": event.id})
        return

    payment = await refund_svc.process_refund_webhook(db, payment_intent_id, refund_status or "succeeded")
    if payment:
        log.info(
            "refund.webhook.processed",
            extra={
                "event_id": event.id,
                "payment_id": payment.id,
                "state": payment.state,
            },
        )
