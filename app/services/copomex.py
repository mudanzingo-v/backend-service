"""
Copomex service — postal code lookups.

Token read from env (`COPOMEX_API_TOKEN`), not from code
(fixes WO-16 from the infra research).
"""
from __future__ import annotations

from typing import Any

import httpx

from app.config import settings
from app.core.logging import get_logger
from app.core.exceptions import ValidationError


log = get_logger(__name__)


async def lookup_postal_code(postal_code: str) -> dict[str, Any]:
    """
    Lookup `postal_code` via the Copomex API.

    Returns the raw response (passthrough). The DynamoDB `locations`
    table is not used in this service — see
    `docs/research/business-domain.md` §6.2 for the rationale.
    """
    if not settings.copomex_api_token:
        raise ValidationError("COPOMEX_API_TOKEN is not set")

    url = f"{settings.copomex_api_url}/query/get_colonia_por_cp/{postal_code}"
    params = {"token": settings.copomex_api_token}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
        if resp.status_code >= 400:
            log.error("Copomex error %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()
        return resp.json()
