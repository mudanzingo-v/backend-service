"""Audit log model — tracks who changed what for SAT compliance."""
from __future__ import annotations

from app.core.database import Base
from app.models._audit import AuditLog

__all__ = ["AuditLog"]
