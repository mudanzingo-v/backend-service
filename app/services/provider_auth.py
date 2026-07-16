"""
Provider auth service — self-registration, email verification, JWT login.

Three public functions:

- `register_provider(db, body)` — validates input, hashes password, persists Provider
- `verify_email(db, token)` — verifies the magic-link JWT, activates provider
- `login_provider(db, email, password)` — validates credentials, returns JWT
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError, ValidationError
from app.core.logging import get_logger
from app.models import Provider
from app.services.copomex import lookup_postal_code

log = get_logger(__name__)

# SAT RFC regex: persona moral (3 chars) or persona física (4 chars) + 6 digits + 3 alphanumeric
_RFC_REGEX = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")

# Password complexity: ≥ 10 chars, at least 1 uppercase, 1 lowercase, 1 digit
_PASSWORD_REGEX = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{10,}$")


def _hash_password(password: str) -> str:
    """Hash a password with bcrypt (salt自动生成)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    """Check a password against its bcrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def _make_verification_token(provider_id: str) -> str:
    """Issue a short-lived JWT (24 h) for email verification."""
    now = datetime.utcnow()
    payload = {
        "sub": provider_id,
        "purpose": "email_verification",
        "iat": now,
        "exp": now + timedelta(hours=24),
    }
    return jwt.encode(payload, settings.stripe_secret_key or "dev-secret", algorithm="HS256")


def _make_login_token(provider_id: str) -> str:
    """Issue a longer-lived JWT (7 days) for provider API access."""
    now = datetime.utcnow()
    payload = {
        "sub": provider_id,
        "pool": "providers",
        "iat": now,
        "exp": now + timedelta(days=7),
    }
    return jwt.encode(payload, settings.stripe_secret_key or "dev-secret", algorithm="HS256")


async def register_provider(
    db: AsyncSession,
    *,
    email: str,
    phone: str,
    name: str,
    company_name: str,
    rfc: str,
    postal_code: str,
    password: str,
) -> Provider:
    """
    Register a new provider.

    Validates email uniqueness, RFC format, postal code (via Copomex),
    and password complexity. Returns the persisted Provider with
    ``kyc_status="PENDING_KYC"``.
    """
    # ---- Email uniqueness ----
    stmt = select(Provider).where(Provider.email == email)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(f"A provider with email '{email}' already exists")

    # ---- RFC format ----
    rfc_clean = rfc.upper().strip()
    if not _RFC_REGEX.match(rfc_clean):
        raise ValidationError(
            f"Invalid RFC format '{rfc}'. Must be 3-4 letters + 6 digits + 3 alphanumeric "
            "(e.g. XAXX010101000)"
        )

    # ---- Postal code via Copomex ----
    try:
        await lookup_postal_code(postal_code)
    except Exception as exc:
        raise ValidationError(f"Invalid postal code '{postal_code}': {exc}") from exc

    # ---- Password complexity ----
    if not _PASSWORD_REGEX.match(password):
        raise ValidationError(
            "Password must be at least 10 characters with mixed case and a digit"
        )

    # ---- Persist ----
    provider = Provider(
        id=str(uuid.uuid4()),
        email=email,
        phone=phone,
        name=name,
        company_name=company_name,
        rfc=rfc_clean,
        password_hash=_hash_password(password),
        kyc_status="PENDING_KYC",
        active=True,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)

    # ---- Issue verification token ----
    provider.verification_token = _make_verification_token(provider.id)
    await db.commit()
    await db.refresh(provider)

    log.info("Provider registered: id=%s email=%s", provider.id, email)

    return provider


async def verify_email(db: AsyncSession, token: str) -> Provider:
    """
    Verify a provider's email address using the magic-link JWT.

    Returns the Provider with ``verified_at`` set.
    """
    try:
        payload = jwt.decode(
            token,
            settings.stripe_secret_key or "dev-secret",
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise ValidationError(f"Invalid or expired verification token: {exc}") from exc

    if payload.get("purpose") != "email_verification":
        raise ValidationError("Token is not an email verification token")

    provider_id: str | None = payload.get("sub")
    if not provider_id:
        raise ValidationError("Token missing 'sub' claim")

    provider = await db.get(Provider, provider_id)
    if provider is None:
        raise NotFoundError("Provider not found")

    if provider.verified_at is not None:
        # Already verified — idempotent
        return provider

    provider.verified_at = datetime.utcnow()
    provider.verification_token = None
    await db.commit()
    await db.refresh(provider)

    log.info("Provider verified: id=%s email=%s", provider.id, provider.email)
    return provider


async def login_provider(db: AsyncSession, email: str, password: str) -> str:
    """
    Authenticate a provider by email + password.

    Returns a JWT string on success.
    """
    stmt = select(Provider).where(Provider.email == email)
    provider = (await db.execute(stmt)).scalar_one_or_none()
    if provider is None:
        raise UnauthorizedError("Invalid email or password")

    if provider.password_hash is None:
        raise UnauthorizedError(
            "This account uses a different login method (e.g. social login)"
        )

    if not _verify_password(password, provider.password_hash):
        raise UnauthorizedError("Invalid email or password")

    if not provider.active:
        raise UnauthorizedError("Account is deactivated")

    if provider.verified_at is None:
        raise UnauthorizedError("Email not verified. Please check your inbox.")

    token = _make_login_token(provider.id)
    log.info("Provider logged in: id=%s email=%s", provider.id, email)
    return token
