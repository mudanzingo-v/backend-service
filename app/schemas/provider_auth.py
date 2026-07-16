"""
Pydantic schemas for provider auth — registration, verification, login.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class ProviderRegisterBody(BaseModel):
    """Request body for ``POST /api/auth/provider/register``."""

    email: EmailStr
    phone: str = Field(..., min_length=10, max_length=20)
    name: str = Field(..., min_length=1, max_length=255)
    company_name: str = Field(..., min_length=1, max_length=255)
    rfc: str = Field(..., min_length=12, max_length=13)
    postal_code: str = Field(..., min_length=5, max_length=5)
    password: str = Field(..., min_length=10, max_length=128)


class ProviderRegisterResponse(BaseModel):
    """Response body for successful registration."""

    id: str
    email: str
    name: str
    company_name: str
    rfc: str
    kyc_status: str
    message: str = "Provider registered. Check your email to verify your account."


class VerifyEmailResponse(BaseModel):
    """Response body for successful email verification."""

    id: str
    email: str
    verified_at: datetime
    message: str = "Email verified successfully. You can now log in."


class ProviderLoginBody(BaseModel):
    """Request body for ``POST /api/auth/provider/login``."""

    email: EmailStr
    password: str = Field(..., min_length=1)


class ProviderLoginResponse(BaseModel):
    """Response body for successful login."""

    token: str
    provider_id: str
    message: str = "Login successful"
