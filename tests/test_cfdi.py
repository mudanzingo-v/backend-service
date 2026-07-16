"""
CFDI 4.0 invoice tests — capture, stamp, cancel.

Uses mock PAC adapter (MockCfdi) which generates synthetic UUIDs + files.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import Auction, Invoice, Payment, Provider, Quotation
from app.schemas.cfdi import InvoiceCaptureBody
from app.services import invoice as invoice_svc


@pytest.fixture
async def seeded_paid_quotation(db_session: AsyncSession) -> tuple[Quotation, Payment]:
    """A quotation with a PAID payment and a provider with RFC."""
    prov = Provider(
        id=str(uuid.uuid4()),
        email=f"{uuid.uuid4().hex[:8]}@provider.com",
        name="CFDI Provider",
        rfc="AAA010101AAA",
        active=True,
        kyc_status="APPROVED",
    )
    q = Quotation(
        client_name="CFDI Client",
        client_phone="+525511111111",
        client_email="cfdi.client@example.com",
        state="QUOTED",
    )
    db_session.add(prov)
    db_session.add(q)
    await db_session.commit()
    await db_session.refresh(prov)
    await db_session.refresh(q)

    auction = Auction(
        quotation_id=q.id,
        provider_id=prov.id,
        price_load=Decimal("100.00"),
        subtotal=Decimal("100.00"),
        mobbit_fee=Decimal("5.00"),
        iva=Decimal("16.80"),
        transaction_fee=Decimal("6.09"),
        total=Decimal("127.89"),
        state="ACCEPTED",
    )
    db_session.add(auction)
    await db_session.commit()
    await db_session.refresh(auction)

    payment = Payment(
        quotation_id=q.id,
        auction_id=auction.id,
        type="STRIPE",
        state="PAID",
        amount=Decimal("127.89"),
        currency="MXN",
    )
    db_session.add(payment)
    await db_session.commit()
    await db_session.refresh(payment)

    return q, payment


async def test_capture_invoice_creates_pending_invoice(
    db_session: AsyncSession,
    seeded_paid_quotation: tuple[Quotation, Payment],
) -> None:
    """`capture_invoice` creates a PENDING invoice with correct amounts."""
    q, payment = seeded_paid_quotation
    body = InvoiceCaptureBody(rfc="XAXX010101000", cfdi_use="G03")

    invoice = await invoice_svc.capture_invoice(db_session, q.id, body)

    assert invoice.status == "PENDING"
    assert invoice.rfc_receptor == "XAXX010101000"
    assert invoice.rfc_emisor == "AAA010101AAA"
    assert invoice.payment_id == payment.id
    assert invoice.quotation_id == q.id
    assert float(invoice.total) == 127.89
    assert float(invoice.subtotal) == pytest.approx(110.25, rel=0.01)
    assert float(invoice.iva) == pytest.approx(17.64, rel=0.01)


async def test_capture_invoice_without_paid_payment_raises_validation(
    db_session: AsyncSession,
) -> None:
    """Capturing invoice without a PAID payment raises ValidationError."""
    q = Quotation(
        client_name="No Payment",
        client_phone="+525511111111",
        client_email="no.payment@example.com",
        state="DRAFT",
    )
    db_session.add(q)
    await db_session.commit()
    await db_session.refresh(q)

    body = InvoiceCaptureBody(rfc="XAXX010101000")
    with pytest.raises(ValidationError) as exc_info:
        await invoice_svc.capture_invoice(db_session, q.id, body)
    assert "no paid payment" in str(exc_info.value).lower()


async def test_capture_duplicate_invoice_raises_conflict(
    db_session: AsyncSession,
    seeded_paid_quotation: tuple[Quotation, Payment],
) -> None:
    """Capturing a second invoice for the same payment raises ConflictError."""
    q, _ = seeded_paid_quotation
    body = InvoiceCaptureBody(rfc="XAXX010101000")
    await invoice_svc.capture_invoice(db_session, q.id, body)

    with pytest.raises(ConflictError) as exc_info:
        await invoice_svc.capture_invoice(db_session, q.id, body)
    assert "already exists" in str(exc_info.value)


async def test_stamp_invoice_transitions_to_stamped(
    db_session: AsyncSession,
    seeded_paid_quotation: tuple[Quotation, Payment],
) -> None:
    """`stamp_invoice` transitions a PENDING invoice to STAMPED via MockCfdi."""
    q, _ = seeded_paid_quotation
    body = InvoiceCaptureBody(rfc="XAXX010101000")
    invoice = await invoice_svc.capture_invoice(db_session, q.id, body)

    stamped = await invoice_svc.stamp_invoice(db_session, invoice.id)

    assert stamped.status == "STAMPED"
    assert stamped.cfdi_uuid is not None
    assert stamped.pdf_url is not None
    assert stamped.xml_url is not None
    assert stamped.stamped_at is not None


async def test_stamp_nonexistent_invoice_raises_not_found(
    db_session: AsyncSession,
) -> None:
    """Stamping a non-existent invoice raises NotFoundError."""
    with pytest.raises(NotFoundError):
        await invoice_svc.stamp_invoice(db_session, "nonexistent")


async def test_stamp_already_stamped_invoice_raises_conflict(
    db_session: AsyncSession,
    seeded_paid_quotation: tuple[Quotation, Payment],
) -> None:
    """Stamping an already STAMPED invoice raises ConflictError."""
    q, _ = seeded_paid_quotation
    body = InvoiceCaptureBody(rfc="XAXX010101000")
    invoice = await invoice_svc.capture_invoice(db_session, q.id, body)
    await invoice_svc.stamp_invoice(db_session, invoice.id)

    with pytest.raises(ConflictError) as exc_info:
        await invoice_svc.stamp_invoice(db_session, invoice.id)
    assert "Cannot stamp" in str(exc_info.value)


async def test_cancel_stamped_invoice(
    db_session: AsyncSession,
    seeded_paid_quotation: tuple[Quotation, Payment],
) -> None:
    """`cancel_invoice` transitions STAMPED to CANCELLED."""
    q, _ = seeded_paid_quotation
    body = InvoiceCaptureBody(rfc="XAXX010101000")
    invoice = await invoice_svc.capture_invoice(db_session, q.id, body)
    invoice = await invoice_svc.stamp_invoice(db_session, invoice.id)

    cancelled = await invoice_svc.cancel_invoice(db_session, invoice.id)
    assert cancelled.status == "CANCELLED"


async def test_cancel_pending_invoice_raises_conflict(
    db_session: AsyncSession,
    seeded_paid_quotation: tuple[Quotation, Payment],
) -> None:
    """Cancelling a PENDING (not stamped) invoice raises ConflictError."""
    q, _ = seeded_paid_quotation
    body = InvoiceCaptureBody(rfc="XAXX010101000")
    invoice = await invoice_svc.capture_invoice(db_session, q.id, body)

    with pytest.raises(ConflictError):
        await invoice_svc.cancel_invoice(db_session, invoice.id)


async def test_mock_cfdi_generates_valid_files(
    db_session: AsyncSession,
    seeded_paid_quotation: tuple[Quotation, Payment],
) -> None:
    """MockCfdi generates XML and PDF files on disk."""
    from pathlib import Path

    q, _ = seeded_paid_quotation
    body = InvoiceCaptureBody(rfc="XAXX010101000")
    invoice = await invoice_svc.capture_invoice(db_session, q.id, body)
    stamped = await invoice_svc.stamp_invoice(db_session, invoice.id)

    xml_path = Path(stamped.xml_url)  # type: ignore[arg-type]
    pdf_path = Path(stamped.pdf_url)  # type: ignore[arg-type]
    assert xml_path.exists(), f"XML file not found: {xml_path}"
    assert pdf_path.exists(), f"PDF file not found: {pdf_path}"
    content = xml_path.read_text()
    assert "cfdi:Comprobante" in content
    assert stamped.cfdi_uuid in content
