"""Audit service tests."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser
from app.services.audit import _compute_changes, log_action


@pytest.fixture
def test_actor() -> AuthUser:
    return AuthUser(sub="admin-123", pool="rccm", claims={"sub": "admin-123", "pool": "rccm"})


async def test_log_action_creates_entry(
    db_session: AsyncSession,
    test_actor: AuthUser,
) -> None:
    """`log_action` creates an AuditLog entry with correct fields."""
    entry = await log_action(
        db_session,
        actor=test_actor,
        action="quotation.cancel",
        entity_type="quotation",
        entity_id="q-123",
        before={"state": "QUOTED"},
        after={"state": "CANCELLED"},
    )

    assert entry.actor_id == "admin-123"
    assert entry.actor_pool == "rccm"
    assert entry.action == "quotation.cancel"
    assert entry.entity_type == "quotation"
    assert entry.entity_id == "q-123"
    assert entry.before == {"state": "QUOTED"}
    assert entry.after == {"state": "CANCELLED"}
    assert entry.changes == {"state": {"from": "QUOTED", "to": "CANCELLED"}}


async def test_log_action_without_before_after(
    db_session: AsyncSession,
    test_actor: AuthUser,
) -> None:
    """`log_action` works without before/after snapshots."""
    entry = await log_action(
        db_session,
        actor=test_actor,
        action="provider.register",
        entity_type="provider",
        entity_id="prov-123",
    )

    assert entry.action == "provider.register"
    assert entry.before is None
    assert entry.after is None
    assert entry.changes is None


def test_compute_changes() -> None:
    """`_compute_changes` detects added, removed, and modified fields."""
    before = {"name": "Old", "email": "old@test.com", "active": True}
    after = {"name": "New", "email": "old@test.com", "phone": "+5255"}

    changes = _compute_changes(before, after)

    assert changes["name"] == {"from": "Old", "to": "New"}
    assert "email" not in changes  # unchanged
    assert changes["active"] == {"from": True, "to": None}  # removed
    assert changes["phone"] == {"from": None, "to": "+5255"}  # added
