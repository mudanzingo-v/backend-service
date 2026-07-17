"""
CFDI service — invoice creation and lifecycle management.

Flow:
1. Capture RFC + usoCFDI from B2C client (capture_invoice)
2. On payment confirmation, auto-stamp via PAC (stamp_invoice)
3. On order cancellation, cancel CFDI if already stamped (cancel_invoice)
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models import Auction, Invoice, Payment, Provider, Quotation
from app.schemas.cfdi import InvoiceCaptureBody
from app.services.cfdi import InvoiceData, get_cfdi_adapter

log = get_logger(__name__)


async def capture_invoice(
    db: AsyncSession,
    quotation_id: str,
    body: InvoiceCaptureBody,
) -> Invoice:
    """
    Capture RFC + usoCFDI for a quotation and create a PENDING invoice.
    Only allowed after payment is confirmed (state=PAID).
    """
    quotation = await db.get(Quotation, quotation_id)
    if quotation is None:
        raise NotFoundError(f"Quotation {quotation_id} not found")

    # Find the PAID payment for this quotation
    stmt = select(Payment).where(
        Payment.quotation_id == quotation_id,
        Payment.state == "PAID",
    )
    payment = (await db.execute(stmt)).scalar_one_or_none()
    if payment is None:
        raise ValidationError(
            "Cannot create invoice: no PAID payment found for this quotation"
        )

    # Check for existing invoice
    stmt = select(Invoice).where(Invoice.payment_id == payment.id)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"An invoice already exists for payment {payment.id}")

    # Find the provider's RFC (emisor)
    auction = await db.get(Auction, payment.auction_id) if payment.auction_id else None
    provider_rfc = settings.cognito_client_mobbit  # fallback
    if auction:
        provider = await db.get(Provider, auction.provider_id)
        if provider and provider.rfc:
            provider_rfc = provider.rfc

    # Calculate amounts from the payment
    total = payment.amount or Decimal("0.00")
    subtotal = (total / Decimal("1.16")).quantize(Decimal("0.01"))
    iva = (total - subtotal).quantize(Decimal("0.01"))

    invoice = Invoice(
        payment_id=payment.id,
        quotation_id=quotation_id,
        rfc_emisor=provider_rfc.upper(),
        rfc_receptor=body.rfc.upper(),
        cfdi_use=body.cfdi_use,
        subtotal=subtotal,
        iva=iva,
        total=total,
        status="PENDING",
    )
    db.add(invoice)
    await db.commit()
    await db.refresh(invoice)

    log.info("Invoice captured: id=%s quotation=%s", invoice.id, quotation_id)
    return invoice


async def stamp_invoice(db: AsyncSession, invoice_id: str) -> Invoice:
    """Send a PENDING invoice to the PAC for stamping."""
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFoundError(f"Invoice {invoice_id} not found")

    if invoice.status != "PENDING":
        raise ConflictError(f"Cannot stamp invoice in state '{invoice.status}'")

    cfdi = get_cfdi_adapter()
    data = InvoiceData(
        rfc_emisor=invoice.rfc_emisor,
        rfc_receptor=invoice.rfc_receptor,
        cfdi_use=invoice.cfdi_use,
        payment_method=invoice.payment_method,
        subtotal=invoice.subtotal,
        iva=invoice.iva,
        total=invoice.total,
        description=f"Servicios de mudanza - {invoice.quotation_id[:8]}",
    )

    try:
        result = await cfdi.stamp(data)
        invoice.status = "STAMPED"
        invoice.cfdi_uuid = result.cfdi_uuid
        invoice.xml_url = result.xml_url
        invoice.pdf_url = result.pdf_url
        invoice.stamped_at = result.stamped_at
    except Exception as exc:
        invoice.status = "FAILED"
        invoice.error_message = str(exc)
        log.error("CFDI stamping failed: invoice=%s error=%s", invoice_id, exc)

    await db.commit()
    await db.refresh(invoice)
    return invoice


async def cancel_invoice(db: AsyncSession, invoice_id: str) -> Invoice:
    """Cancel a STAMPED invoice via the PAC."""
    invoice = await db.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFoundError(f"Invoice {invoice_id} not found")

    if invoice.status != "STAMPED":
        raise ConflictError(f"Cannot cancel invoice in state '{invoice.status}'")

    cfdi = get_cfdi_adapter()
    await cfdi.cancel(invoice.cfdi_uuid or "")

    invoice.status = "CANCELLED"
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def auto_stamp_on_payment(db: AsyncSession, payment_id: str) -> Invoice | None:
    """Automatically create and stamp an invoice when a payment is confirmed."""
    stmt = select(Invoice).where(Invoice.payment_id == payment_id)
    invoice = (await db.execute(stmt)).scalar_one_or_none()
    if invoice:
        # Already exists — try to stamp if pending
        if invoice.status == "PENDING":
            return await stamp_invoice(db, invoice.id)
        return invoice
    return None
