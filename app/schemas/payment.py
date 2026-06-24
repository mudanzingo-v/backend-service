"""Payment schemas + Location passthrough."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PaymentCreateStripe(BaseModel):
    """Admin creates a Stripe payment preference for a quotation."""

    model_config = ConfigDict(extra="forbid")
    id_auction: str


# Backward-compat alias for code paths still wired to the MP naming.
# The admin payments endpoint (`app/api/admin/payments.py`) was not
# rewritten as part of PR2 — that lands in PR3 — so it still imports
# `PaymentCreateMP`. We keep the alias so the existing import path
# resolves to the new Stripe-shaped schema. Safe to remove in PR4
# once the admin endpoint is fully migrated and the legacy import
# is gone.
PaymentCreateMP = PaymentCreateStripe


class PaymentCreateDeposit(BaseModel):
    """Admin records a deposit payment."""

    model_config = ConfigDict(extra="forbid")
    id_auction: str
    amount: Decimal
    reference: str | None = None


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    quotation_id: str
    auction_id: str | None = None
    type: str
    state: str
    amount: Decimal | None = None
    currency: str
    stripe_payment_intent_id: str | None = None
    stripe_checkout_session_id: str | None = None
    stripe_payment_status: str | None = None
    created_at: datetime
    updated_at: datetime


class LocationRead(BaseModel):
    """Mirrors the Copomex response (passthrough)."""

    model_config = ConfigDict(extra="allow")
