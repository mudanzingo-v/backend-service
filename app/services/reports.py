"""
Reports service — operational metrics for the admin dashboard.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Auction, Payment, Provider, Quotation


async def dashboard_stats(db: AsyncSession) -> dict:
    """Return key metrics for the admin dashboard."""
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)

    # Total quotations
    total_quotations = await db.execute(select(func.count(Quotation.id)))
    total_quotations = total_quotations.scalar() or 0

    # Quotations by state (last 30 days)
    stmt = (
        select(Quotation.state, func.count(Quotation.id))
        .where(Quotation.created_at >= thirty_days_ago)
        .group_by(Quotation.state)
    )
    result = await db.execute(stmt)
    quotations_by_state = {row[0] or "UNKNOWN": row[1] for row in result}

    # Active providers
    result = await db.execute(
        select(func.count(Provider.id)).where(Provider.active.is_(True))
    )
    total_providers = result.scalar() or 0

    # KYC approved providers
    result = await db.execute(
        select(func.count(Provider.id)).where(Provider.kyc_status == "APPROVED")
    )
    kyc_approved = result.scalar() or 0

    # Total revenue
    result = await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.state == "PAID")
    )
    total_revenue = float(result.scalar() or 0)

    # Revenue last 30 days
    result = await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.state == "PAID")
        .where(Payment.created_at >= thirty_days_ago)
    )
    revenue_30d = float(result.scalar() or 0)

    # Auctions by state
    result = await db.execute(
        select(Auction.state, func.count(Auction.id)).group_by(Auction.state)
    )
    auctions_by_state = {row[0]: row[1] for row in result}

    # Provider acceptance rate
    result = await db.execute(
        select(func.count(Auction.id)).where(
            Auction.state.in_(["ACCEPTED", "DECLINED"])
        )
    )
    total_decided = result.scalar() or 0
    result = await db.execute(
        select(func.count(Auction.id)).where(Auction.state == "ACCEPTED")
    )
    accepted = result.scalar() or 0
    acceptance_rate = round(accepted / total_decided * 100, 1) if total_decided > 0 else 0.0

    return {
        "quotations": {
            "total": total_quotations,
            "by_state_last_30d": quotations_by_state,
        },
        "providers": {
            "active": total_providers,
            "kyc_approved": kyc_approved,
        },
        "revenue": {
            "total_mxn": total_revenue,
            "last_30_days_mxn": revenue_30d,
        },
        "auctions": {
            "by_state": auctions_by_state,
            "provider_acceptance_rate_pct": acceptance_rate,
        },
    }
