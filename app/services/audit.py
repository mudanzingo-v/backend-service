"""Audit service — log mutations on business entities."""
from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser
from app.core.logging import get_logger
from app.models import AuditLog

log = get_logger(__name__)


async def log_action(
    db: AsyncSession,
    actor: AuthUser,
    action: str,
    entity_type: str,
    entity_id: str,
    *,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Create an audit log entry.

    Args:
        actor: The authenticated user performing the action.
        action: Action name (e.g. ``quotation.cancel``, ``payment.refund``).
        entity_type: Entity type (e.g. ``quotation``, ``payment``).
        entity_id: Entity identifier.
        before: Snapshot of the entity before the change.
        after: Snapshot of the entity after the change.
        request: Optional FastAPI request (extracts IP + user-agent).
    """
    changes = _compute_changes(before, after) if before and after else None

    entry = AuditLog(
        actor_id=actor.sub,
        actor_pool=actor.pool,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        changes=changes,
        ip=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    log.debug("AuditLog: %s %s:%s by %s", action, entity_type, entity_id, actor.sub)
    return entry


def _compute_changes(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Compute the diff between before and after snapshots.

    Returns a dict like ``{"field_name": {"from": ..., "to": ...}}``.
    """
    changes: dict[str, dict[str, Any]] = {}
    all_keys = set(before.keys()) | set(after.keys())
    for key in all_keys:
        b = before.get(key)
        a = after.get(key)
        if b != a:
            changes[key] = {"from": b, "to": a}
    return changes
