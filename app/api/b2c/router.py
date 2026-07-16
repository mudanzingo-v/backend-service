"""B2C router aggregator."""
from fastapi import APIRouter

from app.api.b2c import auctions, catalog, invoices, quotations, ratings

b2c_router = APIRouter(prefix="/api/b2c")
b2c_router.include_router(quotations.router)
b2c_router.include_router(auctions.router)
b2c_router.include_router(auctions.quotation_auctions_router)
b2c_router.include_router(auctions.root_router)
b2c_router.include_router(auctions.checkout_session_router)
b2c_router.include_router(catalog.router)
b2c_router.include_router(invoices.router)
b2c_router.include_router(ratings.router)
