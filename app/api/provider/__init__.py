"""
Provider-facing endpoints.

The provider app (`front-provider`) talks to these endpoints. Auth
requires a JWT from the `providers` Cognito user pool (or dev mode).
"""
from fastapi import APIRouter

from app.api.provider import auctions, profile

provider_router = APIRouter(prefix="/api/provider")
provider_router.include_router(auctions.router)
provider_router.include_router(profile.router)
