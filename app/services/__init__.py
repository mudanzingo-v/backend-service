"""Service modules for the mobbit backend.

`stripe` is the active payment gateway (the only one — see
`stripe-payment-replacement`). Re-exporting here keeps the import surface
small:

    from app.services import stripe
"""
from __future__ import annotations

from app.services import stripe

__all__ = ["stripe"]
