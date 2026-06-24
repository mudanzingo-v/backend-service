"""
Provider profile endpoint.

Returns the provider's own info from the JWT (provider_id = sub).
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthUser, current_provider
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models import Provider
from app.schemas import ProviderRead

router = APIRouter(prefix="/profile", tags=["provider:profile"])


@router.get(
    "",
    response_model=ProviderRead,
    summary="Get my provider profile",
)
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(current_provider),
) -> ProviderRead:
    """Returns the provider record matching the JWT's sub. In dev mode
    the sub is `settings.dev_provider_id`."""
    stmt = select(Provider).where(Provider.id == user.sub)
    result = await db.execute(stmt)
    provider = result.scalar_one_or_none()
    if provider is None:
        raise NotFoundError(f"Provider {user.sub} not found")
    return ProviderRead.model_validate(provider)
