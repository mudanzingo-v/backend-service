"""
Refund tests — Stripe refund + webhook + admin endpoint.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import Payment, Provider, Quotation
from app.services import refund as refund_svc


@pytest.fixture
async def seeded_paid_payment(db_session: AsyncSession) -> Payment:
    """A PAID payment with a mock Stripe PaymentIntent."""
    prov = Provider(
        id=str(uuid.uuid4()),
        email=f"{uuid.uuid4().hex[:8]}@provider.com",
        name="Refund Provider",
        active=True,
    )
    q = Quotation(
        client_name="Refund Client",
        client_phone="+525511111111",
        client_email="refund@example.com",
    )
    db_session.add(prov)
    db_session.add(q)
    await db_session.commit()
    await db_session.refresh(prov)
    await db_session.refresh(q)

    payment = Payment(
        quotation_id=q.id,
        type="STRIPE",
        state="PAID",
        amount=Decimal("127.89"),
        currency="MXN",
        stripe_payment_intent_id=f"pi_test_{uuid.uuid4().hex[:12]}",
    )
    db_session.add(payment)
    await db_session.commit()
    await db_session.refresh(payment)
    return payment


async def test_refund_full_payment(
    db_session: AsyncSession,
    seeded_paid_payment: Payment,
) -> None:
    """`refund_payment` transitions PAID → REFUNDED."""
    payment = await refund_svc.refund_payment(db_session, seeded_paid_payment.id)
    assert payment.state == "REFUNDED"


async def test_refund_partial_payment(
    db_session: AsyncSession,
    seeded_paid_payment: Payment,
) -> None:
    """`refund_payment` with amount_cents transitions to PARTIAL_REFUNDED."""
    payment = await refund_svc.refund_payment(
        db_session, seeded_paid_payment.id, amount_cents=5000
    )
    assert payment.state == "PARTIAL_REFUNDED"


async def test_refund_nonexistent_payment_raises_not_found(
    db_session: AsyncSession,
) -> None:
    """Refunding a non-existent payment raises NotFoundError."""
    with pytest.raises(NotFoundError):
        await refund_svc.refund_payment(db_session, "nonexistent")


async def test_refund_non_paid_payment_raises_conflict(
    db_session: AsyncSession,
    seeded_paid_payment: Payment,
) -> None:
    """Refunding an already refunded payment raises ConflictError."""
    await refund_svc.refund_payment(db_session, seeded_paid_payment.id)
    with pytest.raises(ConflictError):
        await refund_svc.refund_payment(db_session, seeded_paid_payment.id)


async def test_refund_without_stripe_id_raises_validation(
    db_session: AsyncSession,
) -> None:
    """Refunding a payment without stripe_payment_intent_id raises ValidationError."""
    q = Quotation(
        client_name="No Stripe",
        client_phone="+525511111111",
        client_email="no.stripe@example.com",
    )
    db_session.add(q)
    await db_session.commit()

    p = Payment(
        quotation_id=q.id,
        type="DEPOSIT",
        state="PAID",
        amount=Decimal("100.00"),
        currency="MXN",
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    with pytest.raises(ValidationError) as exc_info:
        await refund_svc.refund_payment(db_session, p.id)
    assert "no stripe paymentintent" in str(exc_info.value).lower()


async def test_refund_webhook_updates_state(
    db_session: AsyncSession,
    seeded_paid_payment: Payment,
) -> None:
    """`process_refund_webhook` updates payment state via webhook."""
    payment = await refund_svc.process_refund_webhook(
        db_session,
        payment_intent_id=seeded_paid_payment.stripe_payment_intent_id,  # type: ignore[arg-type]
        refund_status="succeeded",
    )
    assert payment is not None
    assert payment.state == "REFUNDED"


async def test_refund_webhook_unknown_payment(
    db_session: AsyncSession,
) -> None:
    """`process_refund_webhook` returns None for unknown PaymentIntent."""
    result = await refund_svc.process_refund_webhook(
        db_session,
        payment_intent_id="pi_unknown_123",
        refund_status="succeeded",
    )
    assert result is None
