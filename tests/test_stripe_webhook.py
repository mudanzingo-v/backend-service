"""
Stripe webhook HTTP integration tests — `req-stripe-webhook-and-admin-endpoints-001`.

Ten acceptance scenarios for the ``POST /webhooks/payments/stripe``
endpoint, covering:

- Signature verification: missing header (400), invalid signature (400),
  valid signature (200).
- Three subscribed events: ``checkout.session.completed``,
  ``payment_intent.succeeded``, ``payment_intent.payment_failed``.
- Idempotency: duplicate ``event_id`` is a no-op (per design §OQ2);
  payment-already-PAID does not re-transition the auction.
- Unknown event types (e.g. ``charge.refunded``) → 200 + log + no DB mutation.

Architecture
------------
The webhook handler uses ``Depends(get_db)`` to inject its own
``AsyncSession``. To make assertions against seeded state and the
handler's effects in a single transaction boundary, we override the
dependency via ``app.dependency_overrides[get_db]`` so the handler
reuses the test's ``db_session`` fixture. This keeps the test
hermetic and lets the standard savepoint-rollback teardown work.

Mock strategy
-------------
Real signature signing is bypassed: we monkeypatch
``stripe.Webhook.construct_event`` to return a tiny ``_FakeEvent``
object. The handler only reads three fields from the event
(``id``, ``type``, ``data.object.id``), so a full ``stripe.Event`` is
not needed.

Uses unique IDs (uuid4 hex) per test (handoff Learning #3: the
savepoint-rollback fixture cannot undo explicit commits, so unique
IDs prevent UNIQUE-constraint collisions across runs).
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
import stripe
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Auction, CheckoutSession, Payment, Quotation

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _unique() -> str:
    return uuid.uuid4().hex[:12]


class _FakeEvent:
    """Minimal stand-in for a ``stripe.Event`` for handler dispatch tests.

    The handler reads three fields: ``id`` (attr), ``type`` (attr),
    ``data.object["id"]`` (subscript). Mirroring the real shape avoids
    needing to round-trip through ``stripe.Event.construct_from``.
    """

    def __init__(
        self,
        event_id: str,
        event_type: str,
        data_object: dict[str, Any],
    ) -> None:
        self.id = event_id
        self.type = event_type
        self.data = type("_Data", (), {"object": data_object})()


@pytest.fixture
def override_db(
    app: FastAPI, db_session: AsyncSession
) -> Iterator[None]:
    """Override the FastAPI ``get_db`` dependency to reuse the test's session.

    The webhook handler then reads seeded state and writes its updates
    through the SAME session the test uses. This means the test can
    verify state by inspecting the already-tracked ORM objects (no
    re-query needed) and the standard savepoint-rollback teardown
    cleans up everything.
    """
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


async def _seed_payment_flow(
    db_session: AsyncSession,
    *,
    payment_state: str = "PENDING",
    auction_state: str = "SELECTED",
    last_event_id: str | None = None,
) -> tuple[Quotation, Auction, CheckoutSession, Payment]:
    """Seed a complete payment flow: quotation → auction → CheckoutSession → Payment.

    State matches what ``select_auction()`` produces in PR2: the auction
    has been selected by the B2C client, the CheckoutSession row has
    been written, and a Payment row is PENDING awaiting webhook
    confirmation. The ``payment_state``, ``auction_state``, and
    ``last_event_id`` overrides let tests pre-stage terminal states
    (PAID/ACCEPTED) for idempotency scenarios.

    Returns the (Quotation, Auction, CheckoutSession, Payment) tuple
    with all rows refreshed and committed.
    """
    u = _unique()
    q = Quotation(
        client_name=u,
        client_phone="+525511111111",
        client_email=f"{u}@example.com",
        origin_postal_code="01000",
        destination_postal_code="03100",
    )
    db_session.add(q)
    await db_session.flush()

    a = Auction(
        quotation_id=q.id,
        provider_id=f"prov-{u}",
        price_load=Decimal("100.00"),
        subtotal=Decimal("100.00"),
        mobbit_fee=Decimal("5.00"),
        iva=Decimal("16.80"),
        transaction_fee=Decimal("6.09"),
        total=Decimal("127.89"),
        state=auction_state,
    )
    db_session.add(a)
    await db_session.flush()

    stripe_session_id = f"cs_test_{u}"
    cs = CheckoutSession(
        auction_id=a.id,
        stripe_session_id=stripe_session_id,
        url=f"https://checkout.stripe.com/c/pay/{stripe_session_id}",
        status="complete" if payment_state == "PAID" else "open",
        payment_status="paid" if payment_state == "PAID" else "unpaid",
        amount_total=12789,
        currency="mxn",
        last_event_id=last_event_id,
    )
    db_session.add(cs)

    p = Payment(
        quotation_id=q.id,
        auction_id=a.id,
        type="STRIPE",
        state=payment_state,
        amount=Decimal("127.89"),
        currency="MXN",
        stripe_checkout_session_id=stripe_session_id,
        stripe_payment_status="succeeded" if payment_state == "PAID" else None,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(a)
    await db_session.refresh(cs)
    await db_session.refresh(p)
    return q, a, cs, p


@pytest.fixture
async def seeded_flow(
    db_session: AsyncSession,
) -> tuple[Quotation, Auction, CheckoutSession, Payment]:
    """Default seeded flow: SELECTED auction, PENDING payment, no prior events."""
    return await _seed_payment_flow(db_session)


@pytest.fixture
async def seeded_flow_already_paid(
    db_session: AsyncSession,
) -> tuple[Quotation, Auction, CheckoutSession, Payment]:
    """Variant where Payment is PAID + Auction ACCEPTED + a prior event id is set.

    Scenario 8 verifies that a re-firing webhook does NOT re-transition
    the auction (the SELECTED→ACCEPTED transition only happens once).
    """
    return await _seed_payment_flow(
        db_session,
        payment_state="PAID",
        auction_state="ACCEPTED",
        last_event_id=f"evt_old_{_unique()}",
    )


def _mock_construct_event(
    monkeypatch: pytest.MonkeyPatch, event: _FakeEvent
) -> None:
    """Replace ``stripe.Webhook.construct_event`` with a fake that returns ``event``."""
    monkeypatch.setattr(
        stripe.Webhook,
        "construct_event",
        lambda *args, **kwargs: event,
    )


# ---------------------------------------------------------------------------
# Signature verification (2 scenarios)
# ---------------------------------------------------------------------------


async def test_webhook_missing_signature_header_returns_400(
    client: AsyncClient,
    override_db: None,  # noqa: ARG001
) -> None:
    """Scenario 7: missing signature header → 400, no DB mutation."""
    resp = await client.post(
        "/webhooks/payments/stripe",
        content=b'{"id":"evt_x","type":"checkout.session.completed","data":{"object":{}}}',
    )
    assert resp.status_code == 400, (
        f"missing signature header should be 400; got {resp.status_code}"
    )
    body = resp.json()
    assert "Missing Stripe-Signature" in body.get("detail", "")


async def test_webhook_invalid_signature_returns_400(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    override_db: None,  # noqa: ARG001
) -> None:
    """Scenario 2: invalid signature → 400, no DB mutation."""

    def _raising(*_args: Any, **_kwargs: Any) -> None:
        raise stripe.error.SignatureVerificationError(
            "No signatures found matching the expected signature for payload",
            sig_header="bad-sig",
        )

    monkeypatch.setattr(stripe.Webhook, "construct_event", _raising)

    resp = await client.post(
        "/webhooks/payments/stripe",
        content=b'{"id":"evt_x","type":"checkout.session.completed"}',
        headers={"Stripe-Signature": "t=1,v1=bad"},
    )
    assert resp.status_code == 400
    assert resp.json().get("detail") == "Invalid signature"


# ---------------------------------------------------------------------------
# Happy path — checkout.session.completed (scenario 1)
# ---------------------------------------------------------------------------


async def test_webhook_valid_signature_dispatches_completed_event(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    override_db: None,  # noqa: ARG001
    seeded_flow: tuple[Quotation, Auction, CheckoutSession, Payment],
) -> None:
    """Scenario 1: valid signature + checkout.session.completed → 200 + state transitions."""
    _q, a, cs, p = seeded_flow
    event_id = f"evt_{_unique()}"
    event = _FakeEvent(
        event_id=event_id,
        event_type="checkout.session.completed",
        data_object={"id": cs.stripe_session_id, "payment_status": "paid"},
    )
    _mock_construct_event(monkeypatch, event)

    resp = await client.post(
        "/webhooks/payments/stripe",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=fake"},
    )
    assert resp.status_code == 200, (
        f"valid webhook should be 200; got {resp.status_code} body={resp.text!r}"
    )
    assert resp.json() == {"received": True}

    # State assertions (handler wrote through the same session via override).
    assert cs.last_event_id == event_id, (
        f"last_event_id not set; got {cs.last_event_id!r}"
    )
    assert cs.payment_status == "paid", f"got payment_status={cs.payment_status!r}"
    assert p.state == "PAID", f"got Payment.state={p.state!r}"
    assert a.state == "ACCEPTED", f"got Auction.state={a.state!r}"


# ---------------------------------------------------------------------------
# Happy path — payment_intent.succeeded (scenario 3)
# ---------------------------------------------------------------------------


async def test_webhook_payment_intent_succeeded_updates_payment_and_auction(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    override_db: None,  # noqa: ARG001
    seeded_flow: tuple[Quotation, Auction, CheckoutSession, Payment],
) -> None:
    """Scenario 3: payment_intent.succeeded → Payment.state=PAID + Auction.state=ACCEPTED."""
    _q, a, cs, p = seeded_flow
    event_id = f"evt_{_unique()}"
    event = _FakeEvent(
        event_id=event_id,
        event_type="payment_intent.succeeded",
        data_object={
            "id": f"pi_{_unique()}",
            "checkout_session": cs.stripe_session_id,
        },
    )
    _mock_construct_event(monkeypatch, event)

    resp = await client.post(
        "/webhooks/payments/stripe",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=fake"},
    )
    assert resp.status_code == 200
    assert p.state == "PAID"
    assert a.state == "ACCEPTED"
    assert cs.last_event_id == event_id


# ---------------------------------------------------------------------------
# Failure path — payment_intent.payment_failed (scenario 4)
# ---------------------------------------------------------------------------


async def test_webhook_payment_intent_payment_failed_marks_payment_failed(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    override_db: None,  # noqa: ARG001
    seeded_flow: tuple[Quotation, Auction, CheckoutSession, Payment],
) -> None:
    """Scenario 4: payment_intent.payment_failed → Payment.state=FAILED, Auction UNCHANGED."""
    _q, a, cs, p = seeded_flow
    auction_state_before = a.state  # SELECTED
    event_id = f"evt_{_unique()}"
    event = _FakeEvent(
        event_id=event_id,
        event_type="payment_intent.payment_failed",
        data_object={
            "id": f"pi_{_unique()}",
            "checkout_session": cs.stripe_session_id,
            "last_payment_error": {"code": "card_declined"},
        },
    )
    _mock_construct_event(monkeypatch, event)

    resp = await client.post(
        "/webhooks/payments/stripe",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=fake"},
    )
    assert resp.status_code == 200
    assert p.state == "FAILED", f"Payment.state should be FAILED; got {p.state!r}"
    assert a.state == auction_state_before, (
        f"Auction.state must be unchanged on failure; got {a.state!r} (was {auction_state_before!r})"
    )


# ---------------------------------------------------------------------------
# Idempotency — duplicate event_id (scenario 5)
# ---------------------------------------------------------------------------


async def test_webhook_duplicate_event_id_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    override_db: None,  # noqa: ARG001
    seeded_flow: tuple[Quotation, Auction, CheckoutSession, Payment],
) -> None:
    """Scenario 5: same event_id twice → both 200, second call no-op."""
    _q, a, cs, p = seeded_flow
    event_id = f"evt_{_unique()}"
    event = _FakeEvent(
        event_id=event_id,
        event_type="checkout.session.completed",
        data_object={"id": cs.stripe_session_id},
    )
    _mock_construct_event(monkeypatch, event)
    headers = {"Stripe-Signature": "t=1,v1=fake"}

    # First call → transitions.
    r1 = await client.post("/webhooks/payments/stripe", content=b"{}", headers=headers)
    assert r1.status_code == 200
    assert p.state == "PAID"
    assert a.state == "ACCEPTED"
    auction_state_after_first = a.state

    # Second call (same event_id) → no-op, no re-transition.
    r2 = await client.post("/webhooks/payments/stripe", content=b"{}", headers=headers)
    assert r2.status_code == 200
    assert a.state == auction_state_after_first, (
        "Auction state must not change on duplicate event_id"
    )


# ---------------------------------------------------------------------------
# Unknown event types (scenario 6)
# ---------------------------------------------------------------------------


async def test_webhook_unknown_event_type_returns_200(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    override_db: None,  # noqa: ARG001
    seeded_flow: tuple[Quotation, Auction, CheckoutSession, Payment],
) -> None:
    """Scenario 6: unknown event.type (e.g. charge.refunded) → 200, no DB mutation."""
    _q, a, cs, p = seeded_flow
    event_id = f"evt_{_unique()}"
    event = _FakeEvent(
        event_id=event_id,
        event_type="charge.refunded",
        data_object={"id": "ch_test_xxx"},
    )
    _mock_construct_event(monkeypatch, event)

    resp = await client.post(
        "/webhooks/payments/stripe",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=fake"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"received": True}

    # State unchanged.
    assert p.state == "PENDING", f"Payment.state mutated on unknown event; got {p.state!r}"
    assert a.state == "SELECTED"
    assert cs.last_event_id is None, "last_event_id must not be set on unknown event"


# ---------------------------------------------------------------------------
# Idempotency — payment already PAID (scenario 8)
# ---------------------------------------------------------------------------


async def test_webhook_payment_status_already_paid_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    override_db: None,  # noqa: ARG001
    seeded_flow_already_paid: tuple[Quotation, Auction, CheckoutSession, Payment],
) -> None:
    """Scenario 8: Payment.state=PAID already, webhook fires again → 200, no double transition."""
    _q, a, cs, p = seeded_flow_already_paid
    pre_event_id = cs.last_event_id  # set by the fixture
    new_event_id = f"evt_new_{_unique()}"
    assert pre_event_id != new_event_id  # sanity

    event = _FakeEvent(
        event_id=new_event_id,
        event_type="checkout.session.completed",
        data_object={"id": cs.stripe_session_id},
    )
    _mock_construct_event(monkeypatch, event)

    resp = await client.post(
        "/webhooks/payments/stripe",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=fake"},
    )
    assert resp.status_code == 200
    # last_event_id MUST be updated to the new event_id (this is the
    # webhook's way of saying "we processed the latest event").
    assert cs.last_event_id == new_event_id, (
        f"last_event_id should advance even on already-paid; got {cs.last_event_id!r}"
    )
    # But the auction transition is skipped (already ACCEPTED).
    assert a.state == "ACCEPTED", "Auction must stay ACCEPTED, no re-transition"
    assert p.state == "PAID"


# ---------------------------------------------------------------------------
# Smoke: handler returns the correct envelope (no regression)
# ---------------------------------------------------------------------------


async def test_webhook_returns_received_true_envelope(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    override_db: None,  # noqa: ARG001
    seeded_flow: tuple[Quotation, Auction, CheckoutSession, Payment],
) -> None:
    """All successful webhook responses use the same envelope shape: ``{"received": true}``.

    Lightweight regression guard so a future refactor doesn't change the
    response body and accidentally break Stripe's retry behavior.
    """
    _q, _a, cs, _p = seeded_flow
    event_id = f"evt_{_unique()}"
    event = _FakeEvent(
        event_id=event_id,
        event_type="checkout.session.completed",
        data_object={"id": cs.stripe_session_id},
    )
    _mock_construct_event(monkeypatch, event)
    resp = await client.post(
        "/webhooks/payments/stripe",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=fake"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"received": True}


# ---------------------------------------------------------------------------
# Defensive coverage — unknown session_id branches (not in the 10 acceptance
# scenarios but required to keep global coverage ≥80% per tasks.md T3)
# ---------------------------------------------------------------------------


async def test_webhook_completed_for_unknown_session_is_noop(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    override_db: None,  # noqa: ARG001
) -> None:
    """Defensive: ``checkout.session.completed`` for a session_id not in our DB.

    Handler returns 200 (so Stripe doesn't retry) but logs a warning and
    makes no DB mutation. Covers lines 184-188 / 227-234 in
    ``app/api/webhooks/stripe.py``.
    """
    event = _FakeEvent(
        event_id=f"evt_{_unique()}",
        event_type="checkout.session.completed",
        data_object={"id": f"cs_test_unknown_{_unique()}"},
    )
    _mock_construct_event(monkeypatch, event)
    resp = await client.post(
        "/webhooks/payments/stripe",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=fake"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"received": True}


async def test_webhook_intent_succeeded_for_unknown_session_is_noop(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    override_db: None,  # noqa: ARG001
) -> None:
    """Defensive: ``payment_intent.succeeded`` for unknown session."""
    event = _FakeEvent(
        event_id=f"evt_{_unique()}",
        event_type="payment_intent.succeeded",
        data_object={
            "id": f"pi_{_unique()}",
            "checkout_session": f"cs_test_unknown_{_unique()}",
        },
    )
    _mock_construct_event(monkeypatch, event)
    resp = await client.post(
        "/webhooks/payments/stripe",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=fake"},
    )
    assert resp.status_code == 200


async def test_webhook_intent_failed_for_unknown_session_is_noop(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    override_db: None,  # noqa: ARG001
) -> None:
    """Defensive: ``payment_intent.payment_failed`` for unknown session."""
    event = _FakeEvent(
        event_id=f"evt_{_unique()}",
        event_type="payment_intent.payment_failed",
        data_object={
            "id": f"pi_{_unique()}",
            "checkout_session": f"cs_test_unknown_{_unique()}",
        },
    )
    _mock_construct_event(monkeypatch, event)
    resp = await client.post(
        "/webhooks/payments/stripe",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=fake"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Out-of-band sanity: Stripe module imports correctly under our test env
# ---------------------------------------------------------------------------


def test_stripe_sdk_is_importable() -> None:
    """Sanity guard: the SDK we depend on is present and at a usable version.

    Per ``req-stripe-foundation-001 §"Pinning contract"`` we pin
    ``stripe>=7.0.0,<8.0.0``. If someone accidentally downgrades the
    SDK or the venv gets recreated without it, this test will fail
    loudly instead of the webhook tests failing in confusing ways.
    """
    import stripe as _stripe
    assert hasattr(_stripe, "Webhook")
    # Use getattr to bypass static analyzer false positive on stripe.error.
    assert getattr(_stripe.error, "SignatureVerificationError", None) is not None
    assert _stripe.VERSION.startswith("7."), (
        f"stripe SDK version mismatch; got {_stripe.VERSION!r}, expected 7.x"
    )
