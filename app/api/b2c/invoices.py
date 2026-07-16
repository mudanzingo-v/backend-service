"""
B2C invoice endpoints — capture RFC and request CFDI after payment.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.schemas.cfdi import InvoiceCaptureBody, InvoiceRead, InvoiceStampResponse
from app.services import invoice as invoice_svc

log = get_logger(__name__)

router = APIRouter(prefix="/api/b2c", tags=["b2c:invoices"])


@router.post(
    "/quotation/{quotation_id}/invoice",
    response_model=InvoiceRead,
    status_code=201,
    summary="Capture RFC and create invoice (B2C)",
)
async def capture_invoice(
    quotation_id: str,
    body: InvoiceCaptureBody,
    db: AsyncSession = Depends(get_db),
) -> InvoiceRead:
    """Capture the client's RFC and create a PENDING invoice for a paid quotation."""
    invoice = await invoice_svc.capture_invoice(db, quotation_id, body)
    return InvoiceRead.model_validate(invoice)


@router.post(
    "/invoice/{invoice_id}/stamp",
    response_model=InvoiceStampResponse,
    summary="Stamp a PENDING invoice via PAC",
)
async def stamp_invoice(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
) -> InvoiceStampResponse:
    """Send a PENDING invoice to the PAC for stamping."""
    invoice = await invoice_svc.stamp_invoice(db, invoice_id)
    return InvoiceStampResponse(
        id=invoice.id,
        status=invoice.status,
        cfdi_uuid=invoice.cfdi_uuid,
        pdf_url=invoice.pdf_url,
        xml_url=invoice.xml_url,
    )


@router.post(
    "/invoice/{invoice_id}/cancel",
    response_model=InvoiceStampResponse,
    summary="Cancel a STAMPED invoice",
)
async def cancel_invoice(
    invoice_id: str,
    db: AsyncSession = Depends(get_db),
) -> InvoiceStampResponse:
    """Cancel a STAMPED invoice via the PAC."""
    invoice = await invoice_svc.cancel_invoice(db, invoice_id)
    return InvoiceStampResponse(
        id=invoice.id,
        status=invoice.status,
        cfdi_uuid=invoice.cfdi_uuid,
        message="Invoice cancelled successfully",
    )
