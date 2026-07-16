"""
Conekta service tests — mock mode, order creation, webhook processing.

All tests run in mock mode (``APP_ENV=local``, no ``CONEKTA_API_KEY``).
"""
from __future__ import annotations

import pytest

from app.services import conekta as conekta_svc


# =============================================================================
# create_order (mock mode)
# =============================================================================


async def test_create_order_mock_returns_synthetic_order() -> None:
    """In mock mode, create_order returns a synthetic order with a checkout URL."""
    result = await conekta_svc.create_order(
        auction_id="auc-123",
        customer_name="Juan Pérez",
        customer_email="juan@example.com",
        customer_phone="+521234567890",
        amount_cents=50000,
        payment_methods=["bank_transfer", "cash"],
        success_url="http://localhost:3000/success",
        failure_url="http://localhost:3000/fail",
    )

    assert result["id"].startswith("ord_mock_")
    assert result["checkout"]["url"].startswith("http://localhost:3051/payment/mock")
    assert result["checkout"]["type"] == "HostedPayment"
    assert "bank_transfer" in result["checkout"]["allowed_payment_methods"]
    assert "cash" in result["checkout"]["allowed_payment_methods"]
    assert result["amount"] == 50000
    assert result["currency"] == "MXN"


async def test_create_order_mock_with_single_method() -> None:
    """Only the requested payment method is allowed."""
    result = await conekta_svc.create_order(
        auction_id="auc-456",
        customer_name="María García",
        customer_email="maria@example.com",
        customer_phone=None,
        amount_cents=100000,
        payment_methods=["cash"],
        success_url="http://localhost:3000/success",
        failure_url="http://localhost:3000/fail",
    )

    assert result["checkout"]["allowed_payment_methods"] == ["cash"]


async def test_create_order_mock_without_phone() -> None:
    """No phone number doesn't break mock mode."""
    result = await conekta_svc.create_order(
        auction_id="auc-789",
        customer_name="Test",
        customer_email="test@example.com",
        customer_phone=None,
        amount_cents=25000,
        payment_methods=["bank_transfer"],
        success_url="http://localhost:3000/success",
        failure_url="http://localhost:3000/fail",
    )

    assert result["checkout"]["url"] is not None
    assert result["amount"] == 25000


# =============================================================================
# process_webhook_event
# =============================================================================


@pytest.fixture
def order_paid_payload() -> dict:
    """Simulated Conekta ``order.paid`` webhook payload."""
    return {
        "type": "order.paid",
        "data": {
            "object": {
                "id": "ord_mock_abc123",
                "payment_status": "paid",
                "amount": 50000,
                "currency": "MXN",
                "charges": {
                    "data": [
                        {
                            "id": "ch_mock_001",
                            "status": "paid",
                            "payment_method": {
                                "type": "bank_transfer",
                                "reference": "1234567890",
                                "service_name": "STP",
                                "bank": "BBVA Bancomer",
                            },
                        }
                    ]
                },
            }
        },
    }


@pytest.fixture
def order_expired_payload() -> dict:
    """Simulated Conekta ``order.expired`` webhook payload."""
    return {
        "type": "order.expired",
        "data": {
            "object": {
                "id": "ord_mock_def456",
                "payment_status": "expired",
                "amount": 50000,
                "currency": "MXN",
                "charges": {"data": []},
            }
        },
    }


async def test_process_webhook_order_paid(
    order_paid_payload: dict,
) -> None:
    """process_webhook_event extracts order.paid correctly."""
    result = conekta_svc.process_webhook_event(order_paid_payload)

    assert result["event"] == "order.paid"
    assert result["order_id"] == "ord_mock_abc123"
    assert result["payment_status"] == "paid"
    assert len(result["charges"]) == 1
    assert result["charges"][0]["payment_method"]["type"] == "bank_transfer"
    assert result["charges"][0]["payment_method"]["reference"] == "1234567890"


async def test_process_webhook_order_expired(
    order_expired_payload: dict,
) -> None:
    """process_webhook_event extracts order.expired correctly."""
    result = conekta_svc.process_webhook_event(order_expired_payload)

    assert result["event"] == "order.expired"
    assert result["order_id"] == "ord_mock_def456"
    assert result["payment_status"] == "expired"
    assert len(result["charges"]) == 0


async def test_process_webhook_unknown_event() -> None:
    """Unknown events pass through without error."""
    payload = {"type": "charge.created", "data": {"object": {"id": "ch_001"}}}
    result = conekta_svc.process_webhook_event(payload)

    assert result["event"] == "charge.created"
    assert result["order_id"] == "ch_001"
