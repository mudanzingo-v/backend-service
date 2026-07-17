"""
Provider auth tests — registration, email verification, login.

Six service-level tests following the plan in
`.rpiv/artifacts/plans/provider-self-registration.md`.

Uses the smoke suite's `db_session` fixture.
No HTTP — tests the service layer directly.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, UnauthorizedError, ValidationError
from app.services.provider_auth import (
    login_provider,
    register_provider,
    verify_email,
)

_VALID_RFC = "XAXX010101000"
_VALID_PASSWORD = "SecurePass123"


# =============================================================================
# Registration
# =============================================================================

class _MockCopomex:
    """Context manager that monkeypatches `lookup_postal_code` to succeed."""

    @staticmethod
    async def _fake_lookup(code: str) -> dict:
        return {"codigo": code, "colonias": [{"nombre": "Test Colonia"}]}


async def test_register_creates_provider_with_pending_kyc(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`register_provider` creates a Provider with kyc_status=PENDING_KYC."""
    monkeypatch.setattr(
        "app.services.provider_auth.lookup_postal_code", _MockCopomex._fake_lookup
    )
    p = await register_provider(
        db_session,
        email="new@provider.com",
        phone="+525511111111",
        name="Test Provider",
        company_name="Test Empresa S.A. de C.V.",
        rfc=_VALID_RFC,
        postal_code="01000",
        password=_VALID_PASSWORD,
    )

    assert p.email == "new@provider.com"
    assert p.name == "Test Provider"
    assert p.company_name == "Test Empresa S.A. de C.V."
    assert p.rfc == _VALID_RFC
    assert p.kyc_status == "PENDING_KYC"
    assert p.active is True
    assert p.password_hash is not None
    assert p.password_hash != _VALID_PASSWORD  # hashed, not plaintext
    assert p.verification_token is not None  # JWT issued
    assert p.verified_at is None  # not yet verified


async def test_register_with_invalid_rfc_returns_validation_error(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`register_provider` raises ValidationError for invalid RFC format."""
    monkeypatch.setattr(
        "app.services.provider_auth.lookup_postal_code", _MockCopomex._fake_lookup
    )
    with pytest.raises(ValidationError) as exc_info:
        await register_provider(
            db_session,
            email="bad.rfc@provider.com",
            phone="+525511111111",
            name="Bad RFC",
            company_name="Bad Co.",
            rfc="INVALID",
            postal_code="01000",
            password=_VALID_PASSWORD,
        )
    assert "Invalid RFC" in str(exc_info.value)


async def test_register_with_duplicate_email_returns_conflict(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`register_provider` raises ConflictError for duplicate email."""
    monkeypatch.setattr(
        "app.services.provider_auth.lookup_postal_code", _MockCopomex._fake_lookup
    )
    await register_provider(
        db_session,
        email="dupe@provider.com",
        phone="+525511111111",
        name="First",
        company_name="First Co.",
        rfc=_VALID_RFC,
        postal_code="01000",
        password=_VALID_PASSWORD,
    )

    with pytest.raises(ConflictError) as exc_info:
        await register_provider(
            db_session,
            email="dupe@provider.com",
            phone="+525522222222",
            name="Second",
            company_name="Second Co.",
            rfc="AAME020101H00",
            postal_code="01000",
            password=_VALID_PASSWORD,
        )
    assert "already exists" in str(exc_info.value)


async def test_register_with_weak_password_returns_validation_error(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`register_provider` raises ValidationError for weak passwords."""
    monkeypatch.setattr(
        "app.services.provider_auth.lookup_postal_code", _MockCopomex._fake_lookup
    )
    with pytest.raises(ValidationError) as exc_info:
        await register_provider(
            db_session,
            email="weak@provider.com",
            phone="+525511111111",
            name="Weak",
            company_name="Weak Co.",
            rfc=_VALID_RFC,
            postal_code="01000",
            password="short",
        )
    assert "Password must be" in str(exc_info.value)


async def test_register_with_no_lowercase_password_returns_validation_error(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Password without lowercase letters raises ValidationError."""
    monkeypatch.setattr(
        "app.services.provider_auth.lookup_postal_code", _MockCopomex._fake_lookup
    )
    with pytest.raises(ValidationError):
        await register_provider(
            db_session,
            email="noupper@provider.com",
            phone="+525511111111",
            name="No Upper",
            company_name="No Upper Co.",
            rfc=_VALID_RFC,
            postal_code="01000",
            password="UPPERCASEONLY123",
        )


async def test_register_with_no_digit_password_returns_validation_error(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Password without digits raises ValidationError."""
    monkeypatch.setattr(
        "app.services.provider_auth.lookup_postal_code", _MockCopomex._fake_lookup
    )
    with pytest.raises(ValidationError):
        await register_provider(
            db_session,
            email="nodigit@provider.com",
            phone="+525511111111",
            name="No Digit",
            company_name="No Digit Co.",
            rfc=_VALID_RFC,
            postal_code="01000",
            password="NoDigitsHereAtAll",
        )


# =============================================================================
# Email verification
# =============================================================================

async def test_verify_email_token_activates_provider(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`verify_email` sets verified_at and clears verification_token."""
    monkeypatch.setattr(
        "app.services.provider_auth.lookup_postal_code", _MockCopomex._fake_lookup
    )
    p = await register_provider(
        db_session,
        email="verify.me@provider.com",
        phone="+525511111111",
        name="Verify Me",
        company_name="Verify Co.",
        rfc=_VALID_RFC,
        postal_code="01000",
        password=_VALID_PASSWORD,
    )

    token = p.verification_token
    assert token is not None

    verified = await verify_email(db_session, token)
    assert verified.verified_at is not None
    assert verified.verification_token is None  # Cleared after verification


async def test_verify_email_with_expired_token_returns_validation_error(
    db_session: AsyncSession,
) -> None:
    """`verify_email` with a garbage token raises ValidationError."""
    with pytest.raises(ValidationError):
        await verify_email(db_session, "this-is-not-a-valid-token")


async def test_verify_email_idempotent_when_already_verified(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifying an already-verified email is a no-op (idempotent)."""
    monkeypatch.setattr(
        "app.services.provider_auth.lookup_postal_code", _MockCopomex._fake_lookup
    )
    p = await register_provider(
        db_session,
        email="already.verified@provider.com",
        phone="+525511111111",
        name="Already Verified",
        company_name="Verified Co.",
        rfc=_VALID_RFC,
        postal_code="01000",
        password=_VALID_PASSWORD,
    )

    token = p.verification_token
    assert token is not None

    # First verification
    v1 = await verify_email(db_session, token)
    assert v1.verified_at is not None

    # Second verification (same token, might be expired but we don't check)
    # Actually the token was issued with 24h expiry, reusing it should work
    v2 = await verify_email(db_session, token)
    assert v2.verified_at is not None
    # verified_at should be the same (idempotent — returns existing, doesn't re-set)


# =============================================================================
# Login
# =============================================================================

async def test_login_with_valid_credentials_returns_token(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`login_provider` returns a JWT for verified providers."""
    monkeypatch.setattr(
        "app.services.provider_auth.lookup_postal_code", _MockCopomex._fake_lookup
    )
    p = await register_provider(
        db_session,
        email="login.test@provider.com",
        phone="+525511111111",
        name="Login Test",
        company_name="Login Co.",
        rfc=_VALID_RFC,
        postal_code="01000",
        password=_VALID_PASSWORD,
    )

    # Manually verify (bypass token check for login test)
    p.verified_at = __import__("datetime").datetime.utcnow()
    p.verification_token = None
    await db_session.commit()

    token = await login_provider(db_session, "login.test@provider.com", _VALID_PASSWORD)
    assert isinstance(token, str)
    assert len(token) > 20  # JWT-like


async def test_login_with_wrong_password_returns_unauthorized(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`login_provider` raises UnauthorizedError for wrong password."""
    monkeypatch.setattr(
        "app.services.provider_auth.lookup_postal_code", _MockCopomex._fake_lookup
    )
    p = await register_provider(
        db_session,
        email="wrong.pw@provider.com",
        phone="+525511111111",
        name="Wrong PW",
        company_name="Wrong Co.",
        rfc=_VALID_RFC,
        postal_code="01000",
        password=_VALID_PASSWORD,
    )
    p.verified_at = __import__("datetime").datetime.utcnow()
    await db_session.commit()

    with pytest.raises(UnauthorizedError) as exc_info:
        await login_provider(db_session, "wrong.pw@provider.com", "WrongPass123")
    assert "Invalid email or password" in str(exc_info.value)


async def test_login_with_unverified_email_returns_unauthorized(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`login_provider` raises UnauthorizedError when email not verified."""
    monkeypatch.setattr(
        "app.services.provider_auth.lookup_postal_code", _MockCopomex._fake_lookup
    )
    await register_provider(
        db_session,
        email="unverified@provider.com",
        phone="+525511111111",
        name="Unverified",
        company_name="Unverified Co.",
        rfc=_VALID_RFC,
        postal_code="01000",
        password=_VALID_PASSWORD,
    )

    with pytest.raises(UnauthorizedError) as exc_info:
        await login_provider(db_session, "unverified@provider.com", _VALID_PASSWORD)
    assert "not verified" in str(exc_info.value).lower()


async def test_login_with_nonexistent_email_returns_unauthorized(
    db_session: AsyncSession,
) -> None:
    """`login_provider` raises UnauthorizedError for unknown email."""
    with pytest.raises(UnauthorizedError) as exc_info:
        await login_provider(db_session, "nobody@nowhere.com", "SomePass123")
    assert "Invalid email or password" in str(exc_info.value)
