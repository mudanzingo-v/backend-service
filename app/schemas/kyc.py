"""
Pydantic schemas for KYC workflow — document upload and admin actions.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProviderDocumentRead(BaseModel):
    """Response shape for a provider document."""

    id: str
    doc_type: str
    original_name: str | None
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class KycApproveBody(BaseModel):
    """Request body for ``POST /api/admin/provider/{id}/kyc/approve``."""

    note: str | None = Field(default=None, max_length=500)


class KycRejectBody(BaseModel):
    """Request body for ``POST /api/admin/provider/{id}/kyc/reject``."""

    reason: str = Field(..., min_length=1, max_length=1000)


class KycStatusResponse(BaseModel):
    """Response for KYC status changes."""

    id: str
    email: str
    kyc_status: str
    message: str
