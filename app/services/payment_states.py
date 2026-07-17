"""
Payment state machine — states and transitions.

States:
- PENDING: initial state, awaiting payment confirmation
- PAID: payment confirmed via Stripe/Conekta webhook
- FAILED: payment failed (Stripe payment_intent.payment_failed)
- EXPIRED: payment expired (Conekta order.expired)
- REFUNDED: fully refunded (admin action)
- PARTIAL_REFUNDED: partially refunded

Transitions:
    PENDING ──► PAID
             └─► FAILED
             └─► EXPIRED
    PAID ──► REFUNDED
         └─► PARTIAL_REFUNDED
"""
from __future__ import annotations

from app.core.exceptions import ValidationError

# State constants
PAY_PENDING = "PENDING"
PAY_PAID = "PAID"
PAY_FAILED = "FAILED"
PAY_EXPIRED = "EXPIRED"
PAY_REFUNDED = "REFUNDED"
PAY_PARTIAL_REFUNDED = "PARTIAL_REFUNDED"

ALL_PAYMENT_STATES = {
    PAY_PENDING, PAY_PAID, PAY_FAILED,
    PAY_EXPIRED, PAY_REFUNDED, PAY_PARTIAL_REFUNDED,
}

# Explicit transition map
PAYMENT_TRANSITIONS = {
    PAY_PENDING: {PAY_PAID, PAY_FAILED, PAY_EXPIRED},
    PAY_PAID: {PAY_REFUNDED, PAY_PARTIAL_REFUNDED},
    PAY_FAILED: set(),       # terminal
    PAY_EXPIRED: set(),      # terminal
    PAY_REFUNDED: set(),     # terminal
    PAY_PARTIAL_REFUNDED: {PAY_REFUNDED},  # partial → full refund
}


def validate_payment_transition(from_state: str, to_state: str) -> None:
    """Raise ValidationError if the payment state transition is not allowed."""
    allowed = PAYMENT_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise ValidationError(
            f"Cannot transition payment from '{from_state}' to '{to_state}'. "
            f"Allowed: {', '.join(sorted(allowed)) or '(terminal)'}"
        )
