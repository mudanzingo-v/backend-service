"""
Quotation service — business logic for creating and managing quotations.

State machine (Phase 0 decision, 2026-06-16):

    DRAFT → QUOTED → BIDDING → AWARDED → IN_PROGRESS → COMPLETED
            ↘                ↘                ↘
             CANCELLED        REJECTED         FAILED

Transitions are explicit; the only automated transition is `publish` (DRAFT → QUOTED).
For provider visibility, the admin must call `POST /quotation/{id}/publish`.

Wizard progress (`wizard_step`, `wizard_complete`) is tracked separately from
the lifecycle state. The current B2C wizard (10 steps) is reference-only and
will be rewritten — the schema is forward-compatible with any wizard design.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models import Quotation
from app.schemas import (
    QuotationCreateAdmin,
    QuotationCreateB2C,
    QuotationUpdate,
)

# Lifecycle state constants (kept in code so the B2C wizard and admin
# endpoints validate against the same set).
ST_DRAFT = "DRAFT"
ST_QUOTED = "QUOTED"
ST_BIDDING = "BIDDING"
ST_AWARDED = "AWARDED"
ST_IN_PROGRESS = "IN_PROGRESS"
ST_COMPLETED = "COMPLETED"
ST_CANCELLED = "CANCELLED"
ST_REJECTED = "REJECTED"
ST_FAILED = "FAILED"

ALL_STATES = {
    ST_DRAFT, ST_QUOTED, ST_BIDDING, ST_AWARDED,
    ST_IN_PROGRESS, ST_COMPLETED, ST_CANCELLED, ST_REJECTED, ST_FAILED,
}

# Minimum fields a quotation needs before it can be published (DRAFT → QUOTED).
REQUIRED_FOR_PUBLISH = (
    "client_name", "client_phone", "client_email",
    "origin_postal_code", "destination_postal_code",
)


# =============================================================================
# CRUD
# =============================================================================
async def create_quotation_b2c(
    db: AsyncSession, body: QuotationCreateB2C
) -> Quotation:
    """B2C public lead — only contact info (matches the original Lambda)."""
    q = Quotation(
        client_name=body.client_name,
        client_phone=body.client_phone,
        client_email=body.client_email,
        state=ST_DRAFT,  # lifecycle starts in DRAFT
    )
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return q


async def create_quotation_admin(
    db: AsyncSession, body: QuotationCreateAdmin
) -> Quotation:
    """Admin creates a fully-detailed quotation on behalf of a client."""
    q = Quotation(**body.model_dump(exclude_unset=True))
    if q.state is None:
        q.state = ST_DRAFT
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return q


async def get_quotation(db: AsyncSession, quotation_id: str) -> Quotation:
    q = await db.get(Quotation, quotation_id)
    if q is None:
        raise NotFoundError(f"Quotation {quotation_id} not found")
    # Block direct access to synthetic records
    if q.client_email == "synthetic@orphan.local":
        raise NotFoundError(f"Quotation {quotation_id} not found")
    return q


async def update_quotation(
    db: AsyncSession, quotation_id: str, body: QuotationUpdate
) -> Quotation:
    q = await get_quotation(db, quotation_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(q, k, v)
    await db.commit()
    await db.refresh(q)
    return q


async def delete_quotation(db: AsyncSession, quotation_id: str) -> None:
    q = await get_quotation(db, quotation_id)
    await db.delete(q)
    await db.commit()


async def list_quotations(
    db: AsyncSession,
    state: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Quotation]:
    """
    Lists quotations, excluding synthetic records (DDB migration glue).

    Filters by `state` if provided. The state machine is documented in
    the module docstring.
    """
    stmt = select(Quotation).order_by(Quotation.created_at.desc()).limit(limit).offset(offset)
    if state is not None:
        stmt = stmt.where(Quotation.state == state)
    # Exclude synthetic records (FK repair artefacts from the DDB→PG migration)
    stmt = stmt.where(Quotation.client_email != "synthetic@orphan.local")
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_auctions_for_quotation(
    db: AsyncSession, quotation_id: str
) -> list:
    """All auctions submitted for a given quotation."""
    from app.models import Auction
    stmt = select(Auction).where(Auction.quotation_id == quotation_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# =============================================================================
# State machine operations
# =============================================================================
async def publish_quotation(db: AsyncSession, quotation_id: str) -> Quotation:
    """
    Transition a quotation from DRAFT to QUOTED.

    The quotation becomes visible to providers after this call. Validates
    that the minimum required fields are populated. Idempotent: if the
    quotation is already in a later state (QUOTED/BIDDING/...), returns it
    unchanged.

    Raises:
        NotFoundError — quotation doesn't exist (or is synthetic)
        ValidationError — required fields are missing
    """
    q = await get_quotation(db, quotation_id)
    if q.state in (ST_BIDDING, ST_AWARDED, ST_IN_PROGRESS, ST_COMPLETED):
        # Already past publish — leave it as is
        return q
    if q.state in (ST_CANCELLED, ST_REJECTED, ST_FAILED):
        raise ValidationError(
            f"Cannot publish a quotation in terminal state '{q.state}'"
        )
    if q.state == ST_QUOTED:
        # Already published — leave it as is (idempotent)
        return q
    # State is DRAFT (or NULL legacy) — validate minimum fields, then publish
    missing = [f for f in REQUIRED_FOR_PUBLISH if not getattr(q, f, None)]
    if missing:
        raise ValidationError(
            f"Cannot publish: missing required fields: {', '.join(missing)}"
        )
    q.state = ST_QUOTED
    await db.commit()
    await db.refresh(q)
    return q


async def cancel_quotation(db: AsyncSession, quotation_id: str) -> Quotation:
    """Transition to CANCELLED from any non-terminal state."""
    q = await get_quotation(db, quotation_id)
    if q.state in (ST_COMPLETED, ST_CANCELLED, ST_REJECTED, ST_FAILED):
        raise ValidationError(f"Cannot cancel a quotation in state '{q.state}'")
    q.state = ST_CANCELLED
    await db.commit()
    await db.refresh(q)
    return q
