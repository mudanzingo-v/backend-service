"""
Admin router aggregator.
"""
from fastapi import APIRouter

from app.api.admin import auctions, catalog, kyc, payments, providers, quotations, salers, search, stats

admin_router = APIRouter(prefix="/api/admin")
admin_router.include_router(quotations.router)
admin_router.include_router(quotations.assign_provider_router)
admin_router.include_router(catalog.products_router)
admin_router.include_router(catalog.services_router)
admin_router.include_router(catalog.inventory_cat_router)
admin_router.include_router(catalog.inventory_items_router)
admin_router.include_router(catalog.inventory_all_router)
admin_router.include_router(providers.providers_router)
admin_router.include_router(providers.trucks_router)
admin_router.include_router(salers.router)
admin_router.include_router(auctions.router)
admin_router.include_router(auctions.top_auction_router)
admin_router.include_router(payments.quotation_payments_router)
admin_router.include_router(payments.top_payment_router)
admin_router.include_router(stats.router)
admin_router.include_router(kyc.router)
admin_router.include_router(search.router)
