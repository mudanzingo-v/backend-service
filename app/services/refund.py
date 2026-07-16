"""
Refund service — issue refunds for Stripe payments and update local state.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models import Auction, Payment
from app.services import stripe

log = get_logger(__name__)


async def refund_payment(
    db: AsyncSession,
    payment_id: str,
    amount_cents: int | None = None,
    reason: str | None = None,
) -> Payment:
    """
    Issue a refund for a PAID payment.

    Updates local state to REFUNDED (or PARTIAL_REFUNDED if amount_cents
    is less than the full amount). Does NOT revert the Auction state.
    """
    payment = await db.get(Payment, payment_id)
    if payment is None:
        raise NotFoundError(f"Payment {payment_id} not found")

    if payment.state != "PAID":
        raise ConflictError(
            f"Cannot refund payment in state '{payment.state}'. Must be PAID."
        )

    if not payment.stripe_payment_intent_id:
        raise ValidationError("Payment has no Stripe PaymentIntent to refund")

    # Call Stripe
    result = await stripe.refund_payment(
        payment_intent_id=payment.stripe_payment_intent_id,
        amount_cents=amount_cents,
        reason=reason,
    )

    # Determine new state
    if amount_cents is not None:
        payment.state = "PARTIAL_REFUNDED"
    else:
        payment.state = "REFUNDED"

    payment.raw_payload = result  # type: ignore[assignment]
    await db.commit()
    await db.refresh(payment)

    log.info(
        "Payment refunded: id=%s state=%s stripe_refund_id=%s",
        payment_id,
        payment.state,
        result.get("id"),
    )
    return payment


async def process_refund_webhook(
    db: AsyncSession,
    payment_intent_id: str,
    refund_status: str,
) -> Payment | None:
    """
    Process a ``charge.refunded`` webhook event.

    Updates the Payment state based on the refund status from Stripe.
    Returns the updated Payment, or None if no matching payment found.
    """
    stmt = select(Payment).where(
        Payment.stripe_payment_intent_id == payment_intent_id
    )
    payment = (await db.execute(stmt)).scalar_one_or_none()
    if payment is None:
        log.warning(
            "refund.webhook.unknown_payment_intent",
            extra={"payment_intent_id": payment_intent_id},
        )
        return None

    if refund_status == "succeeded":
        payment.state = "REFUNDED"
    elif refund_status == "pending":
        payment.state = "REFUNDED"  # Treat pending as eventual refund
    else:
        log.info(
            "refund.webhook.unexpected_status",
            extra={
                "payment_intent_id": payment_intent_id,
                "refund_status": refund_status,
            },
        )
        return payment

    await db.commit()
    await db.refresh(payment)

    log.info(
        "Payment refunded via webhook: id=%s state=%s",
        payment.id,
        payment.state,
    )
    return payment
