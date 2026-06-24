"""Stats schemas — aggregate counts for the admin dashboard."""
from __future__ import annotations

from pydantic import BaseModel


class Stats(BaseModel):
    """Aggregate counts for the admin dashboard. Single query, single round trip."""

    quotations: int = 0
    auctions: int = 0
    products: int = 0
    services: int = 0
    inventory_items: int = 0
    inventory_categories: int = 0
    providers: int = 0
    salers: int = 0
    payments: int = 0
    trucks: int = 0
