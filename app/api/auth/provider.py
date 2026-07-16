"""
Provider auth endpoints.

- ``POST /api/auth/provider/register`` — self-registration
- ``GET /api/auth/provider/verify-email`` — email verification (magic link)
- ``POST /api/auth/provider/login`` — JWT login
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import get_logger
from app.schemas.provider_auth import (
    ProviderLoginBody,
    ProviderLoginResponse,
    ProviderRegisterBody,
    ProviderRegisterResponse,
    VerifyEmailResponse,
)
from app.services.provider_auth import (
    login_provider,
    register_provider,
    verify_email,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api/auth/provider", tags=["provider-auth"])


@router.post("/register", response_model=ProviderRegisterResponse, status_code=201)
async def register(
    body: ProviderRegisterBody,
    db: AsyncSession = Depends(get_db),
) -> ProviderRegisterResponse:
    """Register a new provider. Returns the provider info and sends a
    verification email (verification token is set on the provider record)."""
    provider = await register_provider(
        db,
        email=body.email,
        phone=body.phone,
        name=body.name,
        company_name=body.company_name,
        rfc=body.rfc,
        postal_code=body.postal_code,
        password=body.password,
    )
    return ProviderRegisterResponse(
        id=provider.id,
        email=provider.email or "",
        name=provider.name or "",
        company_name=provider.company_name or "",
        rfc=provider.rfc or "",
        kyc_status=provider.kyc_status,
    )


@router.get("/verify-email", response_model=VerifyEmailResponse)
async def verify(
    token: str = Query(..., description="JWT verification token from the magic link"),
    db: AsyncSession = Depends(get_db),
) -> VerifyEmailResponse:
    """Verify a provider's email address using the magic-link JWT."""
    provider = await verify_email(db, token)
    return VerifyEmailResponse(
        id=provider.id,
        email=provider.email or "",
        verified_at=provider.verified_at,  # type: ignore[arg-type]
    )


@router.post("/login", response_model=ProviderLoginResponse)
async def login(
    body: ProviderLoginBody,
    db: AsyncSession = Depends(get_db),
) -> ProviderLoginResponse:
    """Authenticate a provider and return a JWT."""
    token = await login_provider(db, body.email, body.password)
    # Decode the token to extract the provider_id
    from jose import jwt as _jwt

    payload = _jwt.get_unverified_claims(token)
    provider_id = payload.get("sub", "")
    return ProviderLoginResponse(token=token, provider_id=provider_id)
