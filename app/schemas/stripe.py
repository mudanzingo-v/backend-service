"""Stripe-specific Pydantic schemas.

Three schemas here:

- `StripeCheckoutSessionCreate` — request body for the admin endpoint
  that creates a Stripe Checkout Session. Empty body by design (the
  admin supplies `quotation_id` + `auction_id` in the URL).
- `StripeWebhookEvent` — typed Stripe event payload for the webhook
  handler. `include_in_schema=False` because Stripe's payload doesn't
  fit OpenAPI conventions and the handler is called by Stripe's
  servers, not by client apps.

PR3 (webhook + admin endpoints) wires these into the FastAPI router.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StripeCheckoutSessionCreate(BaseModel):
    """Request body for creating a Stripe Checkout Session.

    Empty by design: the `quotation_id` is in the URL path and
    `auction_id` (the auction the client selected) is the single field.
    The endpoint pulls the auction's `total` and constructs the Stripe
    line item server-side, so the client cannot inject a price.
    """

    model_config = ConfigDict(extra="forbid")

    id_auction: str = Field(..., description="Auction the client selected (UUID4)")


class StripeWebhookEvent(BaseModel):
    """Typed Stripe event payload for the webhook handler.

    We accept the full `data.object` dict as `Any` (Stripe has dozens
    of event shapes and we only read 3 fields from `data.object`:
    `id`, `payment_status`, `amount_total`). The handler dispatches
    on `type` and reads fields with explicit fallbacks.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(..., description="Stripe event id; used for idempotency")
    type: str = Field(..., description="Event type, e.g. 'checkout.session.completed'")
    data: dict[str, Any] = Field(default_factory=dict, description="Event payload")
    created: int | None = Field(default=None, description="Unix timestamp")
    livemode: bool = Field(default=False, description="True for live events, False for test")
