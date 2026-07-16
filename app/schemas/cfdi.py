"""
Pydantic schemas for CFDI 4.0 invoice capture.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class InvoiceCaptureBody(BaseModel):
    """Request body for invoice capture."""

    rfc: str = Field(
        ...,
        min_length=12,
        max_length=13,
        description="RFC del cliente (receptor). Ej: XAXX010101000",
    )
    cfdi_use: str = Field(
        default="G03",
        min_length=3,
        max_length=4,
        description="Uso del CFDI: G03 (servicios profesionales), P01 (honorarios)",
    )


class InvoiceRead(BaseModel):
    """Response shape for an invoice."""

    id: str
    payment_id: str
    quotation_id: str
    rfc_emisor: str
    rfc_receptor: str
    cfdi_use: str
    subtotal: Decimal
    iva: Decimal
    total: Decimal
    status: str
    cfdi_uuid: str | None
    pdf_url: str | None
    xml_url: str | None
    stamped_at: datetime | None
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InvoiceStampResponse(BaseModel):
    """Response after stamping an invoice."""

    id: str
    status: str
    cfdi_uuid: str | None
    pdf_url: str | None
    xml_url: str | None
    message: str = "Invoice stamped successfully"
