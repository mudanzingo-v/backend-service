"""
Invoice (CFDI) state machine — states and transitions.

States:
- PENDING: initial state, awaiting PAC stamp
- STAMPED: stamped by PAC (SAT-approved UUID assigned)
- FAILED: PAC stamping failed
- CANCELLED: invoice was cancelled after being stamped

Transitions:
    PENDING ──► STAMPED
             └─► FAILED
    STAMPED ──► CANCELLED
"""
from __future__ import annotations

from app.core.exceptions import ValidationError

# State constants
INV_PENDING = "PENDING"
INV_STAMPED = "STAMPED"
INV_CANCELLED = "CANCELLED"
INV_FAILED = "FAILED"

ALL_INVOICE_STATES = {
    INV_PENDING, INV_STAMPED, INV_CANCELLED, INV_FAILED,
}

# Explicit transition map
INVOICE_TRANSITIONS = {
    INV_PENDING: {INV_STAMPED, INV_FAILED},
    INV_STAMPED: {INV_CANCELLED},
    INV_CANCELLED: set(),  # terminal
    INV_FAILED: set(),     # terminal
}


def validate_invoice_transition(from_state: str, to_state: str) -> None:
    """Raise ValidationError if the invoice state transition is not allowed."""
    allowed = INVOICE_TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise ValidationError(
            f"Cannot transition invoice from '{from_state}' to '{to_state}'. "
            f"Allowed: {', '.join(sorted(allowed)) or '(terminal)'}"
        )
