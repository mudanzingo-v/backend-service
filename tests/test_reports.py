"""Reports service tests."""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Auction, Payment, Provider, Quotation
from app.services.reports import dashboard_stats


async def test_dashboard_stats_returns_all_sections(
    db_session: AsyncSession,
) -> None:
    """`dashboard_stats` returns all expected sections."""
    stats = await dashboard_stats(db_session)

    assert "quotations" in stats
    assert "providers" in stats
    assert "revenue" in stats
    assert "auctions" in stats


async def test_dashboard_stats_returns_expected_types(
    db_session: AsyncSession,
) -> None:
    """`dashboard_stats` returns correct types for each metric."""
    import uuid
    p = Provider(id=str(uuid.uuid4()), name="Test Prov", active=True, kyc_status="APPROVED")
    q = Quotation(client_name="T", client_phone="+52", client_email="t@t.com", state="QUOTED")
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
    payment = Payment(
        quotation_id=q.id, auction_id=auction.id,
        type="STRIPE", state="PAID", amount=Decimal("128.00"), currency="MXN",
    )
    db_session.add_all([auction, payment])
    await db_session.commit()

    stats = await dashboard_stats(db_session)

    # Check types and minimum bounds (data may leak from other tests)
    assert isinstance(stats["quotations"]["total"], int)
    assert isinstance(stats["revenue"]["total_mxn"], float)
    assert isinstance(stats["auctions"]["provider_acceptance_rate_pct"], float)
    assert stats["revenue"]["total_mxn"] >= 128.0
