"""
Pricing service unit tests — `req-pricing-coverage-001`.

Five service-level unit tests for `app.services.pricing.compute_price()`.
NO database, NO HTTP, NO fixtures. The pricing module reads
`app.config.settings.pricing_*` once at import time; these tests inherit
the dev `.env` values and assert the formula contract directly.

The dev defaults (verified from `app/config.py`):
    pricing_mobbit_fee                  = 0.05
    pricing_iva                         = 0.16
    pricing_transaction_fee             = 0.05
    pricing_cash_on_delivery_mobbit_fee = 0.15

Formula:
    subtotal            = price_load
    mobbit_fee_value    = subtotal * pricing_mobbit_fee
    iva_value           = (subtotal + mobbit_fee_value) * pricing_iva
    transaction_fee_v   = (subtotal + mobbit_fee_value + iva_value) * pricing_transaction_fee
    total               = subtotal + mobbit_fee_value + iva_value + transaction_fee_v

If cash_on_delivery:
    cash_on_delivery_provider = subtotal      (100% to provider)
    cash_on_delivery_mobbit   = subtotal * (pricing_cash_on_delivery_mobbit_fee + 1)
"""
from decimal import Decimal

from app.services.pricing import PriceBreakdown, compute_price

# Reusable constants — the formula values at the documented dev defaults.
_MOBBIT_FEE_RATE = Decimal("0.05")
_IVA_RATE = Decimal("0.16")
_TX_FEE_RATE = Decimal("0.05")
_COD_MOBBIT_FACTOR = Decimal("1.15")  # 1.0 + pricing_cash_on_delivery_mobbit_fee (0.15)


def test_compute_price_low_subtotal_no_cod() -> None:
    """
    Pin the formula at a low subtotal (100.00).

    mobbit_fee = 100.00 * 0.05       =  5.00
    iva        = (100 + 5) * 0.16    = 16.80
    tx_fee     = (100 + 5 + 16.80) * 0.05 = 6.09
    total      = 100 + 5 + 16.80 + 6.09 = 127.89
    """
    result = compute_price(Decimal("100.00"), cash_on_delivery=False)

    assert isinstance(result, PriceBreakdown), (
        f"compute_price must return a PriceBreakdown; got {type(result).__name__}"
    )
    assert result.subtotal == Decimal("100.00")
    assert result.mobbit_fee == Decimal("5.00")
    assert result.iva == Decimal("16.80")
    assert result.transaction_fee == Decimal("6.09")
    assert result.total == Decimal("127.89")
    assert result.cash_on_delivery_provider is None
    assert result.cash_on_delivery_mobbit is None


def test_compute_price_high_subtotal_quantizes_correctly() -> None:
    """
    Pin Decimal quantization (ROUND_HALF_UP) at a high subtotal (12345.67).

    mobbit_fee = 12345.67 * 0.05     =  617.2835  → quantized to  617.28
    iva        = (12345.67 + 617.28) * 0.16
               = 12962.95 * 0.16     = 2074.072   → quantized to 2074.07
    tx_fee     = (12345.67 + 617.28 + 2074.07) * 0.05
               = 15037.02 * 0.05     =  751.851   → quantized to  751.85
    total      = 12345.67 + 617.28 + 2074.07 + 751.85 = 15788.87

    Also asserts the money-conservation invariant:
    subtotal + mobbit_fee + iva + transaction_fee == total
    (no money is created or destroyed by quantization, modulo rounding).
    """
    result = compute_price(Decimal("12345.67"), cash_on_delivery=False)

    assert result.subtotal == Decimal("12345.67")
    assert result.mobbit_fee == Decimal("617.28")
    assert result.iva == Decimal("2074.07")
    assert result.transaction_fee == Decimal("751.85")
    assert result.total == Decimal("15788.87")
    # Money-conservation invariant: the four pieces sum to the total.
    summed = result.subtotal + result.mobbit_fee + result.iva + result.transaction_fee
    assert summed == result.total, (
        f"money-conservation violated: {summed} != {result.total}"
    )


def test_compute_price_with_cod_breaks_down_provider_and_mobbit() -> None:
    """
    Pin the COD branch.

    When `cash_on_delivery=True`:
      - `cash_on_delivery_provider = subtotal` (100% to provider — the
        setting `pricing_cash_on_delivery_provider_fee` is intentionally
        NOT used here; the production code returns `subtotal` directly).
      - `cash_on_delivery_mobbit = subtotal * (cod_mobbit_fee + 1)`
        = subtotal * 1.15 (because `pricing_cash_on_delivery_mobbit_fee = 0.15`).

    The base formula fields (subtotal, mobbit_fee, iva, transaction_fee,
    total) MUST remain equal to the no-COD values — COD adds the
    breakdown fields but does NOT alter the base price.
    """
    cod_result = compute_price(Decimal("500.00"), cash_on_delivery=True)
    no_cod_result = compute_price(Decimal("500.00"), cash_on_delivery=False)

    # COD-specific breakdown fields.
    assert cod_result.cash_on_delivery_provider == Decimal("500.00"), (
        f"cod_provider must equal subtotal=500.00; "
        f"got {cod_result.cash_on_delivery_provider}"
    )
    assert cod_result.cash_on_delivery_mobbit == Decimal("575.00"), (
        f"cod_mobbit must equal subtotal * 1.15 = 575.00; "
        f"got {cod_result.cash_on_delivery_mobbit}"
    )

    # Base formula fields must be UNCHANGED by the COD flag.
    assert cod_result.subtotal == no_cod_result.subtotal
    assert cod_result.mobbit_fee == no_cod_result.mobbit_fee
    assert cod_result.iva == no_cod_result.iva
    assert cod_result.transaction_fee == no_cod_result.transaction_fee
    assert cod_result.total == no_cod_result.total

    # In the no-COD case, both breakdown fields are None.
    assert no_cod_result.cash_on_delivery_provider is None
    assert no_cod_result.cash_on_delivery_mobbit is None


def test_compute_price_iva_is_calculated_over_subtotal_plus_mobbit_fee() -> None:
    """
    Pin the §5.2 bug-fix invariant: IVA is computed on
    `(subtotal + mobbit_fee)`, NOT on `subtotal` alone.

    This is the single most-load-bearing assertion in this file. The
    original Rust port (see `docs/research/business-domain.md` §5.2) used
    the constant `mobbit_fee` (0.05) inside the IVA formula instead of
    the calculated `mobbit_fee_value`, silently under-taxing each
    transaction. The Python port uses the calculated value; this test
    prevents silent regression.
    """
    result = compute_price(Decimal("1000.00"), cash_on_delivery=False)

    # Sanity: mobbit_fee at 5% of 1000 = 50.
    assert result.mobbit_fee == Decimal("50.00")

    # The invariant: iva = (1000 + 50) * 0.16 = 168.00.
    # NOT iva = 1000 * 0.16 = 160.00 (the original Rust bug).
    expected_iva = (Decimal("1000.00") + Decimal("50.00")) * _IVA_RATE
    assert result.iva == expected_iva.quantize(Decimal("0.01")), (
        f"iva must be (subtotal + mobbit_fee) * pricing_iva; "
        f"expected {expected_iva}, got {result.iva}"
    )
    assert result.iva == Decimal("168.00"), (
        f"iva regression: the §5.2 bug would yield 160.00; "
        f"the fix yields 168.00; got {result.iva}"
    )


def test_compute_price_zero_subtotal_returns_zero_breakdown() -> None:
    """
    Pin the zero-subtotal edge case.

    An empty quotation (e.g., a not-yet-filled B2C lead before any
    items are added) MUST produce a zero breakdown with no
    `ZeroDivisionError` / `InvalidOperation` from decimal arithmetic.
    """
    result = compute_price(Decimal("0.00"), cash_on_delivery=False)

    assert result.subtotal == Decimal("0.00")
    assert result.mobbit_fee == Decimal("0.00")
    assert result.iva == Decimal("0.00")
    assert result.transaction_fee == Decimal("0.00")
    assert result.total == Decimal("0.00")
    assert result.cash_on_delivery_provider is None
    assert result.cash_on_delivery_mobbit is None
