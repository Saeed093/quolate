"""Pure landed-cost math. No I/O, exhaustively unit-tested.

    landed_unit = fx(unit_price) * (1 + duty_pct + lc_pct) + freight_per_unit

All inputs coerced to Decimal for exact arithmetic. Percentages are fractions
(0.10 == 10%).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def to_decimal(value, default: Decimal | None = None) -> Decimal | None:
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def landed_unit_cost(
    fob_unit_price: Decimal | float | int | str,
    *,
    duty_pct: Decimal | float | int | str = 0,
    freight_per_unit: Decimal | float | int | str = 0,
    lc_pct: Decimal | float | int | str = 0,
) -> Decimal:
    """Landed unit cost from an FOB price already in the target currency."""
    fob = to_decimal(fob_unit_price)
    if fob is None:
        raise ValueError("fob_unit_price is required")
    duty = to_decimal(duty_pct, Decimal(0)) or Decimal(0)
    freight = to_decimal(freight_per_unit, Decimal(0)) or Decimal(0)
    lc = to_decimal(lc_pct, Decimal(0)) or Decimal(0)
    return fob * (Decimal(1) + duty + lc) + freight


def spread_pct(values: list[Decimal]) -> Decimal | None:
    """Percentage spread between the highest and lowest of `values`."""
    nums = [v for v in values if v is not None]
    if len(nums) < 2:
        return None
    low = min(nums)
    high = max(nums)
    if low == 0:
        return None
    return (high - low) / low * Decimal(100)
