"""Service modules for the mobbit backend.

`stripe` is the active payment gateway (PR1+ of `stripe-payment-replacement`).
`mercadopago` was the prior gateway; the module is preserved until PR4
deletes it along with `app/api/webhooks/mercadopago.py`.

Re-exporting here keeps the import surface small:
    from app.services import stripe
"""
from __future__ import annotations

from app.services import stripe

__all__ = ["stripe"]
