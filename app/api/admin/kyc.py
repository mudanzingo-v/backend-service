"""
Admin KYC endpoints — approve or reject provider applications.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, current_admin
from app.core.database import get_db
from app.core.logging import get_logger
from app.schemas.kyc import KycApproveBody, KycRejectBody, KycStatusResponse
from app.services import kyc as kyc_svc

log = get_logger(__name__)

router = APIRouter(prefix="/provider/{provider_id}/kyc", tags=["admin:kyc"])


@router.post("/approve", response_model=KycStatusResponse)
async def approve_kyc(
    provider_id: str,
    body: KycApproveBody = KycApproveBody(),
    db: AsyncSession = Depends(get_db),
    _admin: AuthUser = Depends(current_admin),
) -> KycStatusResponse:
    """Approve a provider's KYC application."""
    provider = await kyc_svc.approve_provider(db, provider_id)
    return KycStatusResponse(
        id=provider.id,
        email=provider.email or "",
        kyc_status=provider.kyc_status,
        message="Provider KYC approved",
    )


@router.post("/reject", response_model=KycStatusResponse)
async def reject_kyc(
    provider_id: str,
    body: KycRejectBody,
    db: AsyncSession = Depends(get_db),
    _admin: AuthUser = Depends(current_admin),
) -> KycStatusResponse:
    """Reject a provider's KYC application with a reason."""
    provider = await kyc_svc.reject_provider(db, provider_id, body.reason)
    return KycStatusResponse(
        id=provider.id,
        email=provider.email or "",
        kyc_status=provider.kyc_status,
        message=f"Provider KYC rejected: {body.reason}",
    )
