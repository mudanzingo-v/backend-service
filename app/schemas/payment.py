"""Payment schemas + Location passthrough."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PaymentCreateStripe(BaseModel):
    """Admin creates a Stripe payment preference for a quotation."""

    model_config = ConfigDict(extra="forbid")
    id_auction: str


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
