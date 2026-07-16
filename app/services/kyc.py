"""
KYC service — document upload and admin approval workflow.

Flow:
1. Provider submits documents (ine, rfc_constancia, license, insurance, bank_statement)
2. Provider's kyc_status → SUBMITTED after first document upload
3. Admin approves → kyc_status → APPROVED
4. Admin rejects → kyc_status → REJECTED (with reason)
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models import Provider, ProviderDocument
from app.services.storage import save_document

log = get_logger(__name__)

# Allowed document types
ALLOWED_DOC_TYPES = {"ine", "rfc_constancia", "license", "insurance", "bank_statement"}

# Allowed file extensions for upload
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}

# KYC status constants
KYC_NOT_STARTED = "NOT_STARTED"
KYC_SUBMITTED = "SUBMITTED"
KYC_APPROVED = "APPROVED"
KYC_REJECTED = "REJECTED"

_KYC_TRANSITIONS = {
    KYC_NOT_STARTED: {KYC_SUBMITTED},
    KYC_SUBMITTED: {KYC_APPROVED, KYC_REJECTED},
    KYC_APPROVED: set(),   # terminal
    KYC_REJECTED: set(),   # terminal
}


async def upload_document(
    db: AsyncSession,
    provider_id: str,
    doc_type: str,
    content: bytes,
    original_name: str,
) -> ProviderDocument:
    """
    Upload a KYC document for a provider.

    If this is the first document, sets the provider's kyc_status to SUBMITTED.
    """
    provider = await db.get(Provider, provider_id)
    if provider is None:
        raise NotFoundError(f"Provider {provider_id} not found")

    if not provider.active:
        raise ValidationError("Provider account is not active")

    if provider.kyc_status in (KYC_APPROVED, KYC_REJECTED):
        raise ConflictError(
            f"Cannot upload documents when KYC status is '{provider.kyc_status}'"
        )

    doc_type = doc_type.lower().strip()
    if doc_type not in ALLOWED_DOC_TYPES:
        raise ValidationError(
            f"Invalid document type '{doc_type}'. Allowed: {', '.join(sorted(ALLOWED_DOC_TYPES))}"
        )

    ext = _get_extension(original_name)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file extension '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    file_path = await save_document(provider_id, doc_type, content, original_name)

    doc = ProviderDocument(
        provider_id=provider_id,
        doc_type=doc_type,
        file_path=file_path,
        original_name=original_name,
    )
    db.add(doc)

    # First document upload → SUBMITTED
    if provider.kyc_status == KYC_NOT_STARTED:
        provider.kyc_status = KYC_SUBMITTED

    await db.commit()
    await db.refresh(doc)

    log.info("Document uploaded: provider=%s type=%s path=%s", provider_id, doc_type, file_path)
    return doc


async def approve_provider(db: AsyncSession, provider_id: str) -> Provider:
    """Approve a provider's KYC application."""
    provider = await db.get(Provider, provider_id)
    if provider is None:
        raise NotFoundError(f"Provider {provider_id} not found")

    if provider.kyc_status != KYC_SUBMITTED:
        raise ConflictError(
            f"Cannot approve provider with KYC status '{provider.kyc_status}'. "
            "Must be SUBMITTED."
        )

    provider.kyc_status = KYC_APPROVED
    await db.commit()
    await db.refresh(provider)

    log.info("Provider approved: id=%s", provider_id)
    return provider


async def reject_provider(db: AsyncSession, provider_id: str, reason: str) -> Provider:
    """Reject a provider's KYC application with a reason."""
    if not reason or not reason.strip():
        raise ValidationError("A rejection reason is required")

    provider = await db.get(Provider, provider_id)
    if provider is None:
        raise NotFoundError(f"Provider {provider_id} not found")

    if provider.kyc_status != KYC_SUBMITTED:
        raise ConflictError(
            f"Cannot reject provider with KYC status '{provider.kyc_status}'. "
            "Must be SUBMITTED."
        )

    provider.kyc_status = KYC_REJECTED
    await db.commit()
    await db.refresh(provider)

    log.info("Provider rejected: id=%s reason=%s", provider_id, reason)
    return provider


def _get_extension(filename: str) -> str:
    """Extract the file extension (lowercase)."""
    import os as _os
    return _os.path.splitext(filename)[1].lower()
