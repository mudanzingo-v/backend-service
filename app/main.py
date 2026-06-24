"""
FastAPI application entry point.

Run locally:
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Or via Docker:
    docker compose up
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin.router import admin_router
from app.api.b2c.router import b2c_router
from app.api.provider import provider_router
from app.api.webhooks.mercadopago import router as webhook_router
from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown hooks."""
    setup_logging()
    log = get_logger("app.startup")
    log.info(
        "Starting %s in env=%s on %s:%d",
        settings.app_name, settings.app_env, settings.app_host, settings.app_port,
    )
    log.info("Database: %s", settings.database_url.split("@")[-1])
    log.info("Cognito pools: mobbit=%s providers=%s rccm=%s",
             settings.cognito_user_pool_mobbit,
             settings.cognito_user_pool_providers,
             settings.cognito_user_pool_rccm)
    log.info("Auth skip verification: %s (DO NOT USE IN PROD)", settings.auth_skip_verification)
    yield
    log.info("Shutting down %s", settings.app_name)


app = FastAPI(
    title="Mobbit Backend Service",
    version="0.1.0",
    description=(
        "FastAPI port of the Mobbit B2B/B2C marketplace Rust Lambdas. "
        "See `docs/research/business-domain.md` for the business context "
        "and `docs/research/deployment-drift.md` for the original infra."
    ),
    lifespan=lifespan,
)

# ---- Middleware ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Expose the pagination headers so the front can read X-Total-Count etc.
    # Browsers hide non-simple headers from JS unless they're whitelisted here.
    expose_headers=[
        "X-Total-Count",
        "X-Limit",
        "X-Offset",
        "X-Has-Next",
    ],
)

# ---- Exception handlers ----
register_exception_handlers(app)

# ---- Routers ----
app.include_router(b2c_router)
app.include_router(admin_router)
app.include_router(provider_router)
app.include_router(webhook_router)


# ---- Health check ----
@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "service": settings.app_name, "env": settings.app_env}


@app.get("/", tags=["health"])
async def root() -> dict:
    return {
        "service": settings.app_name,
        "version": "0.1.0",
        "docs": "/docs",
        "b2c_prefix": "/api/b2c",
        "admin_prefix": "/api/admin",
        "provider_prefix": "/api/provider",
        "webhooks_prefix": "/webhooks",
    }
