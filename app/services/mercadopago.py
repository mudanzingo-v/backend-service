"""
MercadoPago service — creates checkout preferences.

Token is read from env (`MERCADOPAGO_ACCESS_TOKEN`), not from code
(fixes WO-16 from the infra research).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx

from app.config import settings
from app.core.logging import get_logger
from app.models import Auction, Quotation

log = get_logger(__name__)


class MercadoPagoError(Exception):
    pass


async def create_preference(
    quotation: Quotation,
    auction: Auction,
    cash_on_delivery: bool = False,
) -> dict[str, Any]:
    """
    Mirrors the original `create_preference` in the Rust Lambda
    (`b2c/auctions/put_update_quotation_status/src/mercadopago.rs`).

    Returns the raw MP response (dict). The fields we care about:
    `id`, `init_point`, `sandbox_init_point`, `date_created`, `client_id`,
    `collector_id`, `operation_type`, `items`, `payer`, `shipments`.

    If `MERCADOPAGO_MOCK=true` (or the token is empty AND `is_local`),
    returns a mock preference that redirects to the B2C frontend's
    `/payment/pending` page. Useful for dev and CI.
    """
    if settings.mercadopago_mock or (not settings.mercadopago_access_token and settings.is_local):
        return _mock_preference(quotation, auction, cash_on_delivery)

    if not settings.mercadopago_access_token:
        raise MercadoPagoError("MERCADOPAGO_ACCESS_TOKEN is not set")

    if cash_on_delivery:
        unit_price = Decimal(auction.cash_on_delivery_mobbit or 0) + Decimal(
            auction.cash_on_delivery_provider or 0
        )
    else:
        unit_price = Decimal(auction.total)

    payload: dict[str, Any] = {
        "items": [
            {
                "id": auction.id,  # NOTE: in the Rust code this was `id_auction` = `id_provider`
                "title": f"Auction {auction.id}",
                "quantity": 1,
                "currency_id": "MXN",
                "unit_price": float(unit_price),
            }
        ],
        "payer": {
            "name": quotation.client_name,
            "phone": {"number": quotation.client_phone or ""},
            "email": quotation.client_email,
            "identification": {},
            "address": {
                "street_name": quotation.origin_adress or "",
                "zip_code": quotation.origin_postal_code or "",
            },
        },
        "shipments": {
            "receiver_address": {
                "zip_code": quotation.origin_postal_code or "",
                "street_name": quotation.origin_adress or "",
            }
        },
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.mercadopago_access_token}",
    }
    url = f"{settings.mercadopago_api_url}/checkout/preferences"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            log.error("MP error %s: %s", resp.status_code, resp.text)
            raise MercadoPagoError(f"MP returned {resp.status_code}: {resp.text}")
        return resp.json()


def _mock_preference(
    quotation: Quotation,
    auction: Auction,
    cash_on_delivery: bool = False,
) -> dict[str, Any]:
    """
    Return a synthetic MP preference for local dev and CI.

    The `init_point` redirects to the B2C frontend's `/payment/pending`
    page with query params so the B2C UI can show a realistic flow.
    """
    import uuid

    if cash_on_delivery:
        unit_price = float(
            Decimal(auction.cash_on_delivery_mobbit or 0)
            + Decimal(auction.cash_on_delivery_provider or 0)
        )
    else:
        unit_price = float(Decimal(auction.total))

    pref_id = f"mock-{uuid.uuid4().hex[:12]}"
    b2c_base = settings.b2c_frontend_url.rstrip("/")
    init_point = (
        f"{b2c_base}/payment/pending?pref_id={pref_id}"
        f"&auction_id={auction.id}&quotation_id={quotation.id}"
        f"&status=mock_redirect"
    )

    return {
        "id": pref_id,
        "init_point": init_point,
        "sandbox_init_point": init_point,
        "date_created": "2026-06-17T12:00:00.000-00:00",
        "client_id": "mock-client-id",
        "collector_id": "mock-collector-id",
        "operation_type": "regular_payment",
        "items": [
            {
                "id": auction.id,
                "title": f"Auction {auction.id[:8]}…",
                "quantity": 1,
                "currency_id": "MXN",
                "unit_price": unit_price,
            }
        ],
        "payer": {
            "name": quotation.client_name,
            "email": quotation.client_email,
            "phone": {"number": quotation.client_phone or ""},
        },
        "shipments": {
            "receiver_address": {
                "zip_code": quotation.origin_postal_code or "",
                "street_name": quotation.origin_adress or "",
            }
        },
        "mock": True,  # marker so the B2C UI can show "this is a mock"
    }
