"""
MercadoPago webhook.

**Status: STUB (matches the original Lambda behaviour)**.

The original `infra-core-t/lambdas/webhooks/payments/mercadopago/notification_webhook/`
has every line of business logic commented out and returns 200 OK with `body = "{}"`.
See `docs/research/business-domain.md` §6.1.

We replicate that behaviour here. To implement it properly:
  1. Validate the X-Signature header (HMAC).
  2. Look up the Payment by `mp_preference_id` (or by external_reference).
  3. If topic=payment, call `GET /v1/payments/{id}` to get the status.
  4. Update the Payment.state and, if APPROVED, mark the Auction as
     ACCEPTED and notify the provider.
"""
from fastapi import APIRouter, Request

from app.core.logging import get_logger

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = get_logger(__name__)


@router.post(
    "/payments/mercadopago",
    summary="MercadoPago payment webhook (STUB)",
    description=(
        "Receives MP notifications. The MVP stub returns 200 OK with empty "
        "body, matching the original Rust lambda. To implement: see the "
        "module docstring."
    ),
)
async def mercadopago_webhook(request: Request) -> dict:
    body = await request.body()
    log.info("MP webhook received: %d bytes (stub — no-op)", len(body))
    return {}
