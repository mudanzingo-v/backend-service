"""
Provider KYC endpoints — document upload for identity verification.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, current_provider
from app.core.database import get_db
from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.schemas.kyc import ProviderDocumentRead
from app.services import kyc as kyc_svc

log = get_logger(__name__)

router = APIRouter(prefix="/kyc", tags=["provider:kyc"])


@router.post("/documents", response_model=ProviderDocumentRead, status_code=201)
async def upload_document(
    doc_type: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    provider: AuthUser = Depends(current_provider),
) -> ProviderDocumentRead:
    """Upload a KYC document. The provider is identified by their auth token.

    Allowed doc_types: ine, rfc_constancia, license, insurance, bank_statement
    Allowed formats: PDF, PNG, JPG
    """
    if file.filename is None:
        raise ValidationError("File must have a filename")

    content = await file.read()
    if len(content) == 0:
        raise ValidationError("Uploaded file is empty")

    if len(content) > 10 * 1024 * 1024:  # 10 MB limit
        raise ValidationError("File too large (max 10 MB)")

    doc = await kyc_svc.upload_document(
        db,
        provider_id=provider.sub,
        doc_type=doc_type,
        content=content,
        original_name=file.filename,
    )

    return ProviderDocumentRead(
        id=doc.id,
        doc_type=doc.doc_type,
        original_name=doc.original_name,
        uploaded_at=doc.uploaded_at,
    )
