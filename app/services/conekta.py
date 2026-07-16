"""
Conekta service — HostedPayment orders for SPEI / OXXO payments.

Mock mode (local dev without credentials): returns a synthetic order
with a fake checkout URL, matching the pattern used by Stripe and CFDI.

Config via env vars:
- CONEKTA_API_KEY (empty + is_local=True → mock mode)
- CONEKTA_WEBHOOK_SECRET (for webhook signature verification)
"""
from __future__ import annotations

import uuid
from typing import Any, Literal

from app.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Allowed payment methods for Conekta's HostedPayment
ConektaPaymentMethod = Literal["bank_transfer", "cash"]


def _is_mock_mode() -> bool:
    """Return True when we should synthesize the order instead of calling Conekta.

    Mock mode triggers when ``conekta_api_key`` is empty AND ``is_local``
    is True.  Local dev and the test suite depend on this branch.
    """
    return settings.is_local and not settings.conekta_api_key


def _mock_order(
    *, auction_id: str, amount_cents: int,
    payment_methods: list[str] | None = None,
) -> dict[str, Any]:
    """Synthesize an Order dict for local dev / CI.

    The ``id`` uses the ``ord_mock_<uuid>`` prefix so test assertions can
    distinguish it from a real Conekta id.
    """
    order_id = f"ord_mock_{uuid.uuid4().hex}"
    checkout_id = uuid.uuid4().hex
    url = (
        f"{settings.b2c_frontend_url}/payment/mock"
        f"?order_id={order_id}&auction_id={auction_id}"
    )
    return {
        "id": order_id,
        "checkout": {
            "id": checkout_id,
            "url": url,
            "type": "HostedPayment",
            "status": "Issued",
            "allowed_payment_methods": payment_methods or ["bank_transfer", "cash"],
        },
        "payment_status": None,
        "amount": amount_cents,
        "currency": "MXN",
    }


async def create_order(
    *,
    auction_id: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str | None,
    amount_cents: int,
    payment_methods: list[ConektaPaymentMethod] | None = None,
    success_url: str,
    failure_url: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a Conekta Order with HostedPayment checkout.

    In mock mode returns a synthetic order dict.  In real mode creates an
    Order via the Conekta Orders API and returns the response.

    Returns a dict with ``id``, ``checkout`` (nested dict with ``url``,
    ``type``, ``status``, ``allowed_payment_methods``), ``payment_status``,
    ``amount``, ``currency``.
    """
    methods = payment_methods or ["bank_transfer", "cash"]

    if _is_mock_mode():
        log.info(
            "conekta.create_order.mock",
            extra={
                "auction_id": auction_id,
                "amount_cents": amount_cents,
                "payment_methods": methods,
            },
        )
        return _mock_order(
            auction_id=auction_id, amount_cents=amount_cents,
            payment_methods=methods,
        )

    from conekta import Configuration, OrdersApi
    from conekta import OrderRequest, CheckoutRequest, Product
    from conekta import OrderRequestCustomerInfo
    from conekta import ApiClient

    config = Configuration(access_token=settings.conekta_api_key)
    client = ApiClient(config)

    api = OrdersApi(client)

    checkout = CheckoutRequest(
        allowed_payment_methods=methods,
        type="HostedPayment",
        success_url=success_url,
        failure_url=failure_url,
        name=f"Mobbit Auction {auction_id}",
    )

    line_items = [
        Product(
            name=f"Mobbit Auction {auction_id}",
            unit_price=amount_cents,
            quantity=1,
        )
    ]

    customer_info = OrderRequestCustomerInfo(
        name=customer_name,
        email=customer_email,
        phone=customer_phone or "",
    )

    order_request = OrderRequest(
        currency="MXN",
        customer_info=customer_info,
        line_items=line_items,
        checkout=checkout,
        metadata=metadata or {},
    )

    try:
        import asyncio

        loop = asyncio.get_running_loop()

        def _create() -> Any:
            return api.create_order(
                order_request=order_request,
                accept_language="es",
            )

        order = await loop.run_in_executor(None, _create)

        return {
            "id": order.id,
            "checkout": {
                "id": order.checkout.id,
                "url": order.checkout.url,
                "type": order.checkout.type,
                "status": order.checkout.status,
                "allowed_payment_methods": order.checkout.allowed_payment_methods,
            },
            "payment_status": order.payment_status,
            "amount": order.amount,
            "currency": order.currency,
        }
    except Exception as exc:
        log.error(
            "conekta.create_order.error",
            extra={"auction_id": auction_id, "error": str(exc)},
        )
        raise


def process_webhook_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Process a Conekta webhook event payload.

    Returns a normalized dict with:
    - ``event``: the event type (e.g. ``"order.paid"``, ``"order.expired"``)
    - ``order_id``: the Conekta order id
    - ``payment_status``: the order's payment status
    - ``charges``: list of charge dicts with ``id``, ``status``, ``payment_method``
    """
    event = payload.get("type", "unknown")
    data = payload.get("data", payload)
    order = data.get("object", data) if isinstance(data, dict) else {}

    order_id = order.get("id", "")
    payment_status = order.get("payment_status", "")
    charges_raw = order.get("charges", {}).get("data", []) if isinstance(order.get("charges"), dict) else []

    charges = []
    for ch in charges_raw:
        pm = ch.get("payment_method", {})
        charges.append({
            "id": ch.get("id"),
            "status": ch.get("status"),
            "payment_method": {
                "type": pm.get("type"),
                "reference": pm.get("reference"),
                "service_name": pm.get("service_name"),
                "bank": pm.get("bank"),
            },
        })

    return {
        "event": event,
        "order_id": order_id,
        "payment_status": payment_status,
        "charges": charges,
    }
