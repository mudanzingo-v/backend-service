"""Rating service tests."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ValidationError
from app.models import Auction, Provider, Quotation
from app.services import rating as rating_svc


@pytest.fixture
async def seeded_accepted_auction(db_session: AsyncSession) -> Auction:
    p = Provider(id=str(uuid.uuid4()), name="Rate Provider", active=True)
    q = Quotation(
        client_name="Rate Client", client_phone="+52", client_email="rate@test.com",
        state="QUOTED",
    )
    db_session.add_all([p, q])
    await db_session.commit()
    await db_session.refresh(p)
    await db_session.refresh(q)

    auction = Auction(
        quotation_id=q.id, provider_id=p.id,
        price_load=Decimal("100"), subtotal=Decimal("100"),
        mobbit_fee=Decimal("5"), iva=Decimal("17"),
        transaction_fee=Decimal("6"), total=Decimal("128"),
        state="ACCEPTED",
    )
    db_session.add(auction)
    await db_session.commit()
    await db_session.refresh(auction)
    return auction


async def test_rate_provider_creates_rating(
    db_session: AsyncSession,
    seeded_accepted_auction: Auction,
) -> None:
    """`rate_provider` creates a rating for an ACCEPTED auction."""
    a = seeded_accepted_auction
    rating = await rating_svc.rate_provider(db_session, a.id, 5, "Excelente servicio")

    assert rating.auction_id == a.id
    assert rating.provider_id == a.provider_id
    assert rating.score == 5
    assert rating.comment == "Excelente servicio"


async def test_rate_provider_duplicate_raises_conflict(
    db_session: AsyncSession,
    seeded_accepted_auction: Auction,
) -> None:
    """Rating an already-rated auction raises ConflictError."""
    a = seeded_accepted_auction
    await rating_svc.rate_provider(db_session, a.id, 4, "Bueno")
    with pytest.raises(ConflictError):
        await rating_svc.rate_provider(db_session, a.id, 5, "Mejor")


async def test_rate_provider_invalid_score_raises_validation(
    db_session: AsyncSession,
    seeded_accepted_auction: Auction,
) -> None:
    """Score outside 1-5 raises ValidationError."""
    a = seeded_accepted_auction
    with pytest.raises(ValidationError):
        await rating_svc.rate_provider(db_session, a.id, 0)
    with pytest.raises(ValidationError):
        await rating_svc.rate_provider(db_session, a.id, 6)


async def test_rate_provider_non_accepted_raises_validation(
    db_session: AsyncSession,
    seeded_accepted_auction: Auction,
) -> None:
    """Rating a non-ACCEPTED auction raises ValidationError."""
    a = seeded_accepted_auction
    a.state = "PENDING"
    await db_session.commit()
    with pytest.raises(ValidationError):
        await rating_svc.rate_provider(db_session, a.id, 3)


async def test_get_provider_rating_summary(
    db_session: AsyncSession,
    seeded_accepted_auction: Auction,
) -> None:
    """`get_provider_rating_summary` returns aggregate stats."""
    a1 = seeded_accepted_auction
    p_id = a1.provider_id

    await rating_svc.rate_provider(db_session, a1.id, 5, "Excelente")

    # Add another auction + rating for the same provider
    q2 = Quotation(client_name="C2", client_phone="+52", client_email="c2@test.com")
    db_session.add(q2)
    await db_session.commit()
    await db_session.refresh(q2)

    a2 = Auction(
        quotation_id=q2.id, provider_id=p_id,
        price_load=Decimal("200"), subtotal=Decimal("200"),
        mobbit_fee=Decimal("10"), iva=Decimal("34"),
        transaction_fee=Decimal("12"), total=Decimal("256"),
        state="ACCEPTED",
    )
    db_session.add(a2)
    await db_session.commit()
    await db_session.refresh(a2)

    await rating_svc.rate_provider(db_session, a2.id, 4, "Buen servicio")

    summary = await rating_svc.get_provider_rating_summary(db_session, p_id)
    assert summary["total_ratings"] == 2
    assert summary["average_score"] == 4.5
    assert summary["distribution"]["4"] == 1
    assert summary["distribution"]["5"] == 1
