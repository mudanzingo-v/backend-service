"""
Conekta webhook — receives events from Conekta and updates Payment state.

Endpoint: ``POST /webhooks/payments/conekta``

Subscribed events:
- ``order.paid`` — primary trigger, marks Payment.state = "PAID"
  and transitions Auction.state from SELECTED → ACCEPTED.
- ``order.expired`` — marks Payment.state = "EXPIRED".
  Auction stays SELECTED; admin can reassign.

Other events return 200 with ``{"received": true}`` (no-op).
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models import Auction, Payment
from app.services.conekta import process_webhook_event

import logging
from fastapi import APIRouter, Depends, Request

log = get_logger(__name__)

WEBHOOK_PATH = "/payments/conekta"

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# State constants matching auction.py
STATE_SELECTED = "SELECTED"
STATE_ACCEPTED = "ACCEPTED"
STATE_PAID = "PAID"
STATE_EXPIRED = "EXPIRED"


@router.post(WEBHOOK_PATH)
async def conekta_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive a Conekta webhook event, validate, and update DB state."""
    payload = await request.json()
    event = process_webhook_event(payload)

    event_type = event["event"]
    order_id = event["order_id"]

    log.info(
        "conekta.webhook.received",
        extra={"event": event_type, "order_id": order_id},
    )

    if event_type in ("order.paid", "order.expired"):
        # Look up the payment by conekta_order_id
        from sqlalchemy import select
        result = await db.execute(
            select(Payment).where(Payment.conekta_order_id == order_id)
        )
        payment = result.scalar_one_or_none()

        if payment is None:
            log.warning(
                "conekta.webhook.payment_not_found",
                extra={"order_id": order_id},
            )
            return {"received": True, "note": "payment not found"}

        if event_type == "order.paid":
            payment.state = STATE_PAID
        elif event_type == "order.expired":
            payment.state = STATE_EXPIRED

        payment.raw_payload = payload

        # Transition auction SELECTED → ACCEPTED on successful payment
        if event_type == "order.paid" and payment.auction_id:
            auction = await db.get(Auction, payment.auction_id)
            if auction and auction.state == STATE_SELECTED:
                auction.state = STATE_ACCEPTED
                log.info(
                    "conekta.webhook.auction_accepted",
                    extra={"auction_id": auction.id, "order_id": order_id},
                )

        await db.commit()
        log.info(
            "conekta.webhook.processed",
            extra={
                "event": event_type,
                "order_id": order_id,
                "payment_id": payment.id,
                "new_state": payment.state,
            },
        )

    return {"received": True, "event": event_type}
