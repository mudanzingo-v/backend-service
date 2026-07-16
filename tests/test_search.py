"""Search service tests."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Quotation
from app.services.search import search_quotations


async def test_search_quotations_by_name(
    db_session: AsyncSession,
) -> None:
    """Search finds quotations by client name."""
    q = Quotation(client_name="Juan Pérez", client_phone="+525511111111", client_email="juan@test.com")
    db_session.add(q)
    await db_session.commit()

    results = await search_quotations(db_session, "Juan")
    assert len(results) >= 1
    assert any(r.client_name == "Juan Pérez" for r in results)


async def test_search_quotations_by_phone(
    db_session: AsyncSession,
) -> None:
    """Search finds quotations by client phone."""
    q = Quotation(client_name="Phone Test", client_phone="+525555555555", client_email="phone@test.com")
    db_session.add(q)
    await db_session.commit()

    results = await search_quotations(db_session, "5555")
    assert len(results) >= 1


async def test_search_quotations_by_address(
    db_session: AsyncSession,
) -> None:
    """Search finds quotations by origin or destination address."""
    q = Quotation(
        client_name="Addr Test", client_phone="+52", client_email="addr@test.com",
        origin_adress="Av. Reforma 123, CDMX",
    )
    db_session.add(q)
    await db_session.commit()

    results = await search_quotations(db_session, "Reforma")
    assert len(results) >= 1


async def test_search_quotations_by_id(
    db_session: AsyncSession,
) -> None:
    """Search finds quotations by partial ID match."""
    import uuid
    q = Quotation(
        client_name="ID Test", client_phone="+52", client_email="id@test.com",
    )
    db_session.add(q)
    await db_session.commit()

    results = await search_quotations(db_session, q.id[:8])
    assert len(results) >= 1


async def test_search_quotations_empty_query_returns_recent(
    db_session: AsyncSession,
) -> None:
    """Empty search query returns recent quotations."""
    q = Quotation(client_name="Recent", client_phone="+52", client_email="recent@test.com")
    db_session.add(q)
    await db_session.commit()

    results = await search_quotations(db_session, "")
    assert len(results) >= 1


async def test_search_quotations_excludes_synthetic(
    db_session: AsyncSession,
) -> None:
    """Search excludes synthetic records."""
    q = Quotation(
        client_name="Synthetic Search", client_phone="+52",
        client_email="synthetic@orphan.local",
    )
    db_session.add(q)
    await db_session.commit()

    results = await search_quotations(db_session, "Synthetic")
    assert all(r.client_email != "synthetic@orphan.local" for r in results)
