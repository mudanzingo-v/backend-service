"""Auction + Preference schemas — request/response models for the auction domain."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuctionItemObject(BaseModel):
    """Original Lambda shape: { id: str, offer: str }."""

    model_config = ConfigDict(extra="forbid")

    id: str
    offer: str


class AuctionCreate(BaseModel):
    """Provider submits an offer (POST /quotation/{id}/auction)."""

    model_config = ConfigDict(extra="forbid")

    services: list[AuctionItemObject] | None = None
    products: list[AuctionItemObject] | None = None
    price_load: str = Field(..., description="Total price of the load (as string, like the original)")
    people: str
    id_truck: str
    cash_on_delivery: str | None = None  # "true" or "false" (matches the original)


class AuctionAdminAssign(BaseModel):
    """Admin assigns a provider to a quotation (with a suggested price).

    Creates a new Auction with state=PENDING and the admin's price as
    the initial bid. The provider can then accept as-is, counter-offer,
    or decline.
    """

    model_config = ConfigDict(extra="forbid")

    admin_budget: Decimal = Field(..., description="Admin's suggested price (MXN)")
    people: str | None = None
    id_truck: str | None = None
    note: str | None = None  # Optional admin note for the provider


class AuctionProviderUpdate(BaseModel):
    """Provider accepts / counters an admin-assigned auction.

    The provider can either:
    - Accept as-is (no body required, or just provider_note)
    - Counter-offer (provide price_load, people, etc.)
    """

    model_config = ConfigDict(extra="forbid")

    price_load: str | None = None  # If set, recalculates subtotal/fees/total
    people: str | None = None
    id_truck: str | None = None
    provider_note: str | None = None
    # If true, the provider is confirming the admin's price (no changes)
    accept_admin_price: bool = False


class AuctionUpdate(BaseModel):
    """Admin updates an existing auction (PUT)."""

    model_config = ConfigDict(extra="forbid")

    services: list[AuctionItemObject] | None = None
    products: list[AuctionItemObject] | None = None
    price_load: str | None = None
    people: str | None = None
    id_truck: str | None = None
    state: str | None = None
    admin_budget: Decimal | None = None
    provider_note: str | None = None


class AuctionSelectBody(BaseModel):
    """B2C client selects an auction (PUT /quotation/{id}/auction)."""

    model_config = ConfigDict(extra="forbid")

    id_auction: str
    cash_on_delivery: str = Field(..., description='"true" or "false"')


class AuctionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    quotation_id: str
    provider_id: str
    price_load: Decimal
    subtotal: Decimal
    mobbit_fee: Decimal
    iva: Decimal
    transaction_fee: Decimal
    total: Decimal
    cash_on_delivery_provider: Decimal | None = None
    cash_on_delivery_mobbit: Decimal | None = None
    people: str | None = None
    id_truck: str | None = None
    state: str
    services: list[Any] | None = None
    products: list[Any] | None = None
    admin_budget: Decimal | None = None
    provider_note: str | None = None
    created_at: datetime
    updated_at: datetime


class CheckoutSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    auction_id: str
    stripe_session_id: str | None = None
    url: str | None = None
    status: str | None = None
    payment_status: str | None = None
    amount_total: int | None = None
    currency: str = "mxn"
    last_event_id: str | None = None
    created_at: datetime
