"""
KYC service tests — document upload, admin approve/reject.

Five service-level tests following the plan.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import Provider
from app.services import kyc as kyc_svc


@pytest.fixture
async def seeded_provider(db_session: AsyncSession) -> Provider:
    """A provider with NOT_STARTED KYC status."""
    p = Provider(
        id=str(uuid.uuid4()),
        email=f"{uuid.uuid4().hex[:8]}@provider.com",
        name="KYC Test Provider",
        kyc_status="NOT_STARTED",
        active=True,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


@pytest.fixture
async def seeded_submitted_provider(db_session: AsyncSession) -> Provider:
    """A provider with SUBMITTED KYC status."""
    p = Provider(
        id=str(uuid.uuid4()),
        email=f"{uuid.uuid4().hex[:8]}@provider.com",
        name="Submitted Provider",
        kyc_status="SUBMITTED",
        active=True,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


# =============================================================================
# Document upload
# =============================================================================

async def test_upload_document_succeeds_with_pdf(
    db_session: AsyncSession,
    seeded_provider: Provider,
) -> None:
    """`upload_document` creates a ProviderDocument and transitions to SUBMITTED."""
    doc = await kyc_svc.upload_document(
        db_session,
        provider_id=seeded_provider.id,
        doc_type="ine",
        content=b"%PDF-1.4 fake pdf content",
        original_name="identificacion.pdf",
    )

    assert doc.doc_type == "ine"
    assert doc.original_name == "identificacion.pdf"
    assert doc.file_path is not None
    assert doc.file_path.endswith(".pdf")
    assert doc.provider_id == seeded_provider.id

    # Provider should now be SUBMITTED
    updated = await db_session.get(Provider, seeded_provider.id)
    assert updated is not None
    assert updated.kyc_status == "SUBMITTED"


async def test_upload_document_multiple_allowed(
    db_session: AsyncSession,
    seeded_provider: Provider,
) -> None:
    """A provider can upload multiple documents (different types)."""
    await kyc_svc.upload_document(
        db_session, seeded_provider.id, "ine",
        content=b"pdf1", original_name="ine.pdf",
    )
    await kyc_svc.upload_document(
        db_session, seeded_provider.id, "license",
        content=b"pdf2", original_name="license.pdf",
    )
    await kyc_svc.upload_document(
        db_session, seeded_provider.id, "bank_statement",
        content=b"pdf3", original_name="bank.pdf",
    )

    # All uploads succeeded — no error
    from sqlalchemy import select

    from app.models import ProviderDocument
    stmt = select(ProviderDocument).where(
        ProviderDocument.provider_id == seeded_provider.id
    )
    result = await db_session.execute(stmt)
    docs = result.scalars().all()
    assert len(docs) == 3


async def test_upload_document_invalid_type_returns_validation_error(
    db_session: AsyncSession,
    seeded_provider: Provider,
) -> None:
    """Unsupported doc_type raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        await kyc_svc.upload_document(
            db_session, seeded_provider.id, "selfie",
            content=b"data", original_name="selfie.jpg",
        )
    assert "Invalid document type" in str(exc_info.value)


async def test_upload_document_unsupported_extension_returns_validation_error(
    db_session: AsyncSession,
    seeded_provider: Provider,
) -> None:
    """Unsupported file extension raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        await kyc_svc.upload_document(
            db_session, seeded_provider.id, "ine",
            content=b"<svg>...</svg>", original_name="doc.svg",
        )
    assert "Unsupported file extension" in str(exc_info.value)


async def test_upload_document_nonexistent_provider_raises_not_found(
    db_session: AsyncSession,
) -> None:
    """Upload for non-existent provider raises NotFoundError."""
    with pytest.raises(NotFoundError):
        await kyc_svc.upload_document(
            db_session, "nonexistent-provider", "ine",
            content=b"data", original_name="doc.pdf",
        )


async def test_upload_document_when_approved_raises_conflict(
    db_session: AsyncSession,
    seeded_provider: Provider,
) -> None:
    """Uploading documents after KYC is approved raises ConflictError."""
    seeded_provider.kyc_status = "APPROVED"
    await db_session.commit()

    with pytest.raises(ConflictError):
        await kyc_svc.upload_document(
            db_session, seeded_provider.id, "ine",
            content=b"data", original_name="doc.pdf",
        )


async def test_upload_document_when_rejected_raises_conflict(
    db_session: AsyncSession,
    seeded_provider: Provider,
) -> None:
    """Uploading documents after KYC is rejected raises ConflictError."""
    seeded_provider.kyc_status = "REJECTED"
    await db_session.commit()

    with pytest.raises(ConflictError):
        await kyc_svc.upload_document(
            db_session, seeded_provider.id, "ine",
            content=b"data", original_name="doc.pdf",
        )


# =============================================================================
# Admin approve / reject
# =============================================================================

async def test_admin_approve_submitted_provider(
    db_session: AsyncSession,
    seeded_submitted_provider: Provider,
) -> None:
    """`approve_provider` transitions SUBMITTED → APPROVED."""
    provider = await kyc_svc.approve_provider(db_session, seeded_submitted_provider.id)

    assert provider.kyc_status == "APPROVED"
    assert provider.id == seeded_submitted_provider.id


async def test_admin_approve_not_submitted_raises_conflict(
    db_session: AsyncSession,
    seeded_provider: Provider,
) -> None:
    """Approving a NOT_STARTED provider raises ConflictError."""
    with pytest.raises(ConflictError) as exc_info:
        await kyc_svc.approve_provider(db_session, seeded_provider.id)
    assert "Cannot approve" in str(exc_info.value)


async def test_admin_reject_submitted_provider(
    db_session: AsyncSession,
    seeded_submitted_provider: Provider,
) -> None:
    """`reject_provider` transitions SUBMITTED → REJECTED."""
    provider = await kyc_svc.reject_provider(
        db_session, seeded_submitted_provider.id, reason="Documentos ilegibles"
    )

    assert provider.kyc_status == "REJECTED"


async def test_admin_reject_without_reason_raises_validation_error(
    db_session: AsyncSession,
    seeded_submitted_provider: Provider,
) -> None:
    """Rejecting without a reason raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        await kyc_svc.reject_provider(
            db_session, seeded_submitted_provider.id, reason=""
        )
    assert "rejection reason is required" in str(exc_info.value)


async def test_admin_reject_not_submitted_raises_conflict(
    db_session: AsyncSession,
    seeded_provider: Provider,
) -> None:
    """Rejecting a NOT_STARTED provider raises ConflictError."""
    with pytest.raises(ConflictError):
        await kyc_svc.reject_provider(
            db_session, seeded_provider.id, reason="Not needed"
        )


async def test_admin_approve_nonexistent_raises_not_found(
    db_session: AsyncSession,
) -> None:
    """Approving a non-existent provider raises NotFoundError."""
    with pytest.raises(NotFoundError):
        await kyc_svc.approve_provider(db_session, "nonexistent-id")


async def test_admin_reject_nonexistent_raises_not_found(
    db_session: AsyncSession,
) -> None:
    """Rejecting a non-existent provider raises NotFoundError."""
    with pytest.raises(NotFoundError):
        await kyc_svc.reject_provider(db_session, "nonexistent-id", reason="N/A")
