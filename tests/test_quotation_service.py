"""
Quotation service tests — `req-quotation-coverage-001`.

Fourteen service-level tests for `app.services.quotation.*`. Uses the
smoke suite's `db_session` fixture for savepoint-rollback isolation
(each test sees a clean DB; no row persists past teardown).

NO HTTP, NO auth. The service layer is auth-agnostic; auth is the
admin-endpoint layer's concern (covered by `test_admin_quotations.py`).

State-machine (per `app.services.quotation` docstring):

    DRAFT → QUOTED → BIDDING → AWARDED → IN_PROGRESS → COMPLETED
            ↘                ↘                ↘
             CANCELLED        REJECTED         FAILED

This file covers the 9 public service functions plus dedicated tests
for the 2 state transitions (`publish_quotation` and
`cancel_quotation`) at the service layer — happy paths, error paths,
and idempotency.
"""
from __future__ import annotations

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models import Quotation
from app.schemas import QuotationCreateAdmin, QuotationCreateB2C, QuotationUpdate
from app.services.quotation import (
    ST_CANCELLED,
    ST_DRAFT,
    ST_QUOTED,
    cancel_quotation,
    create_quotation_admin,
    create_quotation_b2c,
    delete_quotation,
    get_quotation,
    list_auctions_for_quotation,
    list_quotations,
    publish_quotation,
    update_quotation,
)

# ---------------------------------------------------------------------------
# Fixtures (file-local — do NOT add to conftest.py unless reused elsewhere)
# ---------------------------------------------------------------------------

@pytest.fixture
def b2c_body() -> QuotationCreateB2C:
    """Minimal B2C lead — only the 3 contact fields."""
    return QuotationCreateB2C(
        client_name="B2C Test User",
        client_phone="+525512345678",
        client_email="b2c.test@example.com",
    )


@pytest.fixture
def admin_body() -> QuotationCreateAdmin:
    """Fully-detailed admin quotation — all REQUIRED_FOR_PUBLISH fields populated."""
    return QuotationCreateAdmin(
        client_name="Admin Test User",
        client_phone="+525511111111",
        client_email="admin.test@example.com",
        origin_postal_code="01000",
        destination_postal_code="03100",
        origin_adress="Av. Reforma 123",
        destination_adress="Av. Insurgentes Sur 456",
    )


# ---------------------------------------------------------------------------
# CRUD scenarios
# ---------------------------------------------------------------------------

async def test_create_quotation_b2c_minimal_contact_info(
    db_session: AsyncSession,
    b2c_body: QuotationCreateB2C,
) -> None:
    """
    `create_quotation_b2c` writes a row with only the 3 contact fields
    populated; lifecycle starts at `DRAFT`.
    """
    q = await create_quotation_b2c(db_session, b2c_body)

    assert q.client_name == "B2C Test User"
    assert q.client_phone == "+525512345678"
    assert q.client_email == "b2c.test@example.com"
    assert q.state == ST_DRAFT, (
        f"B2C leads must start at DRAFT; got {q.state}"
    )


async def test_create_quotation_admin_with_full_addresses(
    db_session: AsyncSession,
    admin_body: QuotationCreateAdmin,
) -> None:
    """
    `create_quotation_admin` writes a fully-detailed quotation;
    lifecycle defaults to `DRAFT` when `state` is not provided.
    """
    q = await create_quotation_admin(db_session, admin_body)

    assert q.client_name == "Admin Test User"
    assert q.client_phone == "+525511111111"
    assert q.client_email == "admin.test@example.com"
    assert q.origin_postal_code == "01000"
    assert q.destination_postal_code == "03100"
    assert q.origin_adress == "Av. Reforma 123"
    assert q.destination_adress == "Av. Insurgentes Sur 456"
    assert q.state == ST_DRAFT


async def test_get_quotation_happy_path(
    db_session: AsyncSession,
    admin_body: QuotationCreateAdmin,
) -> None:
    """`get_quotation` returns the persisted row for a non-synthetic `client_email`."""
    created = await create_quotation_admin(db_session, admin_body)

    fetched = await get_quotation(db_session, created.id)

    assert fetched.id == created.id
    assert fetched.client_email == admin_body.client_email
    assert fetched.state == ST_DRAFT


async def test_get_quotation_filters_synthetic_records(
    db_session: AsyncSession,
    admin_body: QuotationCreateAdmin,  # noqa: ARG001  (used to ensure fixtures work)
) -> None:
    """
    `get_quotation` MUST raise `NotFoundError` for `client_email="synthetic@orphan.local"`.

    Pinning the migration-glue invariant: DDB→PG synthetic records
    (orphans created during the FK-repair step) never leak through
    the API. A future change to the migration glue MUST update this
    test atomically.
    """
    synthetic = Quotation(
        client_name="Synthetic",
        client_phone="+525500000000",
        client_email="synthetic@orphan.local",
        state=ST_DRAFT,
    )
    db_session.add(synthetic)
    await db_session.commit()
    await db_session.refresh(synthetic)

    with pytest.raises(NotFoundError) as exc_info:
        await get_quotation(db_session, synthetic.id)

    assert "not found" in str(exc_info.value).lower()


async def test_update_quotation_partial_fields_only(
    db_session: AsyncSession,
    admin_body: QuotationCreateAdmin,
) -> None:
    """
    `update_quotation` with a body that sets only `client_phone` MUST
    update only that field (verifies `exclude_unset` semantics).
    """
    created = await create_quotation_admin(db_session, admin_body)
    original_email = created.client_email
    original_name = created.client_name

    update_body = QuotationUpdate(client_phone="+525599999999")
    updated = await update_quotation(db_session, created.id, update_body)

    assert updated.client_phone == "+525599999999"
    # Other fields unchanged.
    assert updated.client_email == original_email
    assert updated.client_name == original_name


async def test_delete_quotation_removes_row(
    db_session: AsyncSession,
    admin_body: QuotationCreateAdmin,
) -> None:
    """
    `delete_quotation` removes the row from the DB; subsequent
    `get_quotation` raises `NotFoundError`.
    """
    created = await create_quotation_admin(db_session, admin_body)
    q_id = created.id

    await delete_quotation(db_session, q_id)

    with pytest.raises(NotFoundError):
        await get_quotation(db_session, q_id)


async def test_list_quotations_default_ordering_and_excludes_synthetic(
    db_session: AsyncSession,
    admin_body: QuotationCreateAdmin,
) -> None:
    """
    `list_quotations` (no filter) excludes synthetic records and orders
    by `created_at DESC` (newest first).

    Assertion strategy: rather than asserting on the absolute count of
    returned rows (which depends on pollution from prior runs that
    bypass the savepoint-rollback), we create 2 real quotations and 1
    synthetic in this test, and verify that (a) the synthetic record
    is excluded from the result, (b) both real records are present,
    and (c) `real_2` (newer) precedes `real_1` in the result list.
    """
    # Create 3 quotations: 2 real (T1, T2) + 1 synthetic (T1.5).
    real_1 = await create_quotation_admin(db_session, admin_body)
    real_2 = await create_quotation_admin(
        db_session,
        QuotationCreateAdmin(
            client_name="Second User",
            client_phone="+525522222222",
            client_email="second@example.com",
            origin_postal_code="02000",
            destination_postal_code="03000",
        ),
    )
    synthetic = Quotation(
        client_name="Synthetic",
        client_phone="+525500000000",
        client_email="synthetic@orphan.local",
        state=ST_DRAFT,
    )
    db_session.add(synthetic)
    await db_session.commit()

    items = await list_quotations(db_session)
    items_by_id = {it.id: it for it in items}

    # Both real records MUST be present.
    assert real_1.id in items_by_id, (
        f"real_1 (id={real_1.id}) missing from list_quotations result"
    )
    assert real_2.id in items_by_id, (
        f"real_2 (id={real_2.id}) missing from list_quotations result"
    )
    # Synthetic record MUST be excluded.
    assert synthetic.id not in items_by_id, (
        f"synthetic record (id={synthetic.id}) leaked through list_quotations; "
        f"the migration-glue filter is broken"
    )
    # Newest first: real_2 precedes real_1.
    idx_1 = items.index(real_1)
    idx_2 = items.index(real_2)
    assert idx_2 < idx_1, (
        f"real_2 (newer) must precede real_1 (older); "
        f"got real_1 at index {idx_1}, real_2 at index {idx_2}"
    )


async def test_list_quotations_filter_by_state(
    db_session: AsyncSession,
    admin_body: QuotationCreateAdmin,
) -> None:
    """
    `list_quotations(state=...)` returns only quotations in the
    requested state.

    Assertion strategy: rather than asserting on the absolute count
    (which depends on pollution), we verify that (a) the quotation
    we forced to QUOTED is in the QUOTED result, (b) the quotation
    we left as DRAFT is in the DRAFT result, (c) neither is in the
    OTHER state's result.
    """
    draft = await create_quotation_admin(db_session, admin_body)
    # Force a different state by direct DB update.
    await db_session.execute(
        update(Quotation).where(Quotation.id == draft.id).values(state=ST_QUOTED)
    )
    await db_session.commit()
    # Create another DRAFT for contrast.
    draft_2 = await create_quotation_admin(
        db_session,
        QuotationCreateAdmin(
            client_name="Third",
            client_phone="+525533333333",
            client_email="third@example.com",
            origin_postal_code="04000",
            destination_postal_code="05000",
        ),
    )

    quoted_items = await list_quotations(db_session, state=ST_QUOTED)
    quoted_ids = {it.id for it in quoted_items}
    draft_items = await list_quotations(db_session, state=ST_DRAFT)
    draft_ids = {it.id for it in draft_items}

    # The forced-QUOTED quotation is in the QUOTED result and not in DRAFT.
    assert draft.id in quoted_ids, (
        f"draft (id={draft.id}, forced to QUOTED) must appear in QUOTED list"
    )
    assert draft.id not in draft_ids, (
        f"draft (id={draft.id}, forced to QUOTED) must NOT appear in DRAFT list"
    )
    # The created-DRAFT quotation is in the DRAFT result and not in QUOTED.
    assert draft_2.id in draft_ids, (
        f"draft_2 (id={draft_2.id}) must appear in DRAFT list"
    )
    assert draft_2.id not in quoted_ids, (
        f"draft_2 (id={draft_2.id}) must NOT appear in QUOTED list"
    )


async def test_list_auctions_for_quotation_returns_empty_when_no_auctions(
    db_session: AsyncSession,
    admin_body: QuotationCreateAdmin,
) -> None:
    """A quotation with no auctions submitted returns an empty list."""
    q = await create_quotation_admin(db_session, admin_body)

    auctions = await list_auctions_for_quotation(db_session, q.id)

    assert auctions == []


# ---------------------------------------------------------------------------
# State-transition scenarios: `publish_quotation`
# ---------------------------------------------------------------------------

async def test_publish_quotation_happy_path_draft_to_quoted(
    db_session: AsyncSession,
    admin_body: QuotationCreateAdmin,
) -> None:
    """
    A DRAFT quotation with all `REQUIRED_FOR_PUBLISH` fields populated
    transitions to `QUOTED` and the change is persisted (re-fetch
    confirms).
    """
    q = await create_quotation_admin(db_session, admin_body)
    assert q.state == ST_DRAFT

    published = await publish_quotation(db_session, q.id)

    assert published.state == ST_QUOTED
    # Re-fetch from DB to confirm persistence (not just in-memory).
    refetched = await get_quotation(db_session, q.id)
    assert refetched.state == ST_QUOTED


async def test_publish_quotation_raises_validation_error_when_required_fields_missing(
    db_session: AsyncSession,
) -> None:
    """
    A DRAFT quotation missing one of `REQUIRED_FOR_PUBLISH` MUST
    raise `ValidationError` listing the missing field. State is
    NOT mutated.
    """
    # Use the SQLAlchemy model directly to create a DRAFT quotation
    # with `origin_postal_code=None` (missing required field, but
    # still nullable in the DB schema; `client_phone`/`client_email`
    # are NOT NULL, so they would be rejected by the DB).
    q = Quotation(
        client_name="Missing Origin",
        client_phone="+525577777777",
        client_email="missing.origin@example.com",
        origin_postal_code=None,
        destination_postal_code="07000",
        state=ST_DRAFT,
    )
    db_session.add(q)
    await db_session.commit()
    await db_session.refresh(q)

    with pytest.raises(ValidationError) as exc_info:
        await publish_quotation(db_session, q.id)

    msg = str(exc_info.value)
    assert "missing required fields" in msg, (
        f"expected 'missing required fields' in error; got: {msg}"
    )
    assert "origin_postal_code" in msg, (
        f"expected the missing field name; got: {msg}"
    )
    # State unchanged.
    refetched = await get_quotation(db_session, q.id)
    assert refetched.state == ST_DRAFT


async def test_publish_quotation_raises_validation_error_from_terminal_state(
    db_session: AsyncSession,
    admin_body: QuotationCreateAdmin,
) -> None:
    """
    Publishing a quotation in a terminal state (`CANCELLED`,
    `REJECTED`, `FAILED`) MUST raise `ValidationError`. The state is
    NOT mutated.
    """
    q = await create_quotation_admin(db_session, admin_body)
    # Force terminal state via direct DB update.
    await db_session.execute(
        update(Quotation).where(Quotation.id == q.id).values(state=ST_CANCELLED)
    )
    await db_session.commit()

    with pytest.raises(ValidationError) as exc_info:
        await publish_quotation(db_session, q.id)

    msg = str(exc_info.value)
    assert "Cannot transition" in msg
    assert ST_CANCELLED in msg
    # State unchanged.
    refetched = await get_quotation(db_session, q.id)
    assert refetched.state == ST_CANCELLED


async def test_publish_quotation_idempotent_when_already_quoted(
    db_session: AsyncSession,
    admin_body: QuotationCreateAdmin,
) -> None:
    """
    Re-publishing a quotation already in `QUOTED` is a no-op (idempotent):
    no exception, state remains `QUOTED`.
    """
    q = await create_quotation_admin(db_session, admin_body)
    published = await publish_quotation(db_session, q.id)
    assert published.state == ST_QUOTED

    # Second publish: no exception.
    republished = await publish_quotation(db_session, q.id)
    assert republished.state == ST_QUOTED


# ---------------------------------------------------------------------------
# State-transition scenarios: `cancel_quotation`
# ---------------------------------------------------------------------------

async def test_cancel_quotation_happy_path_to_cancelled(
    db_session: AsyncSession,
    admin_body: QuotationCreateAdmin,
) -> None:
    """
    A non-terminal quotation (`QUOTED` in this test) transitions to
    `CANCELLED` and persists.
    """
    q = await create_quotation_admin(db_session, admin_body)
    # Move to QUOTED first via the public publish path.
    await publish_quotation(db_session, q.id)

    cancelled = await cancel_quotation(db_session, q.id)

    assert cancelled.state == ST_CANCELLED
    # Persistence check.
    refetched = await get_quotation(db_session, q.id)
    assert refetched.state == ST_CANCELLED


async def test_cancel_quotation_raises_validation_error_from_terminal_state(
    db_session: AsyncSession,
    admin_body: QuotationCreateAdmin,
) -> None:
    """
    Cancelling a quotation in `COMPLETED` (terminal) MUST raise
    `ValidationError`. State is NOT mutated.
    """
    q = await create_quotation_admin(db_session, admin_body)
    # Force terminal state directly.
    await db_session.execute(
        update(Quotation).where(Quotation.id == q.id).values(state="COMPLETED")
    )
    await db_session.commit()

    with pytest.raises(ValidationError) as exc_info:
        await cancel_quotation(db_session, q.id)

    msg = str(exc_info.value)
    assert "Cannot transition" in msg
    assert "COMPLETED" in msg
    # State unchanged.
    refetched = await get_quotation(db_session, q.id)
    assert refetched.state == "COMPLETED"
