"""
Pricing service — translates the hardcoded Rust constants to env-driven
Python (so ops can adjust without redeploying).

Verifies the fix for the `docs/research/business-domain.md` §5.2 bug:
the original Rust used the constant `mobbit_fee` (0.05) inside the
`transaction_fee_value` and `total` formulas instead of the calculated
`mobbit_fee_value`. This implementation uses the calculated value.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from app.config import settings


def _q2(x: Decimal) -> Decimal:
    """Quantize to 2 decimal places (currency)."""
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class PriceBreakdown:
    price_load: Decimal
    subtotal: Decimal
    mobbit_fee: Decimal
    iva: Decimal
    transaction_fee: Decimal
    total: Decimal
    cash_on_delivery_provider: Decimal | None
    cash_on_delivery_mobbit: Decimal | None


def compute_price(
    price_load: Decimal,
    cash_on_delivery: bool = False,
) -> PriceBreakdown:
    """
    Replicates the original pricing formula, with the §5.2 bug fixed:
    the calculated `mobbit_fee_value` is used (not the constant).

    subtotal            = price_load
    mobbit_fee_value    = subtotal * mobbit_fee
    iva_value           = (subtotal + mobbit_fee_value) * iva
    transaction_fee_v   = (subtotal + mobbit_fee_value + iva_value) * tx_fee
    total               = subtotal + mobbit_fee_value + iva_value + tx_fee

    If cash_on_delivery:
        cash_on_delivery_provider = subtotal       (100% to provider)
        cash_on_delivery_mobbit   = subtotal * 1.15 (what the client pays in COD;
                                                     the field name is misleading
                                                     but matches the original schema)
    """
    fee = Decimal(str(settings.pricing_mobbit_fee))
    iva = Decimal(str(settings.pricing_iva))
    tx = Decimal(str(settings.pricing_transaction_fee))
    cod_provider = Decimal(str(settings.pricing_cash_on_delivery_provider_fee))
    cod_mobbit = Decimal(str(settings.pricing_cash_on_delivery_mobbit_fee))

    subtotal = _q2(price_load)
    mobbit_fee_value = _q2(subtotal * fee)
    iva_value = _q2((subtotal + mobbit_fee_value) * iva)
    transaction_fee_value = _q2((subtotal + mobbit_fee_value + iva_value) * tx)
    total = _q2(subtotal + mobbit_fee_value + iva_value + transaction_fee_value)

    cod_provider_value: Decimal | None = None
    cod_mobbit_value: Decimal | None = None
    if cash_on_delivery:
        cod_provider_value = _q2(subtotal)
        # Original: subtotal * 0.15 + subtotal = subtotal * 1.15
        cod_mobbit_value = _q2(subtotal * (cod_mobbit + Decimal("1")))

    return PriceBreakdown(
        price_load=subtotal,
        subtotal=subtotal,
        mobbit_fee=mobbit_fee_value,
        iva=iva_value,
        transaction_fee=transaction_fee_value,
        total=total,
        cash_on_delivery_provider=cod_provider_value,
        cash_on_delivery_mobbit=cod_mobbit_value,
    )
