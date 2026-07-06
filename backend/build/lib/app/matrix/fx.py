"""Static FX conversion (zero-cost).

Rates are bundled in rates.json (units of currency per 1 unit of the base, USD).
Projects may override individual rates via landed_cost_defaults.fx_overrides.

# TODO(cloud): swap the static table for a live FX API behind the same interface.
"""
from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

_RATES_PATH = Path(__file__).with_name("rates.json")


class UnknownCurrency(Exception):
    """Raised when a currency has no known rate and no override."""


@lru_cache
def _load() -> tuple[str, dict[str, Decimal]]:
    data = json.loads(_RATES_PATH.read_text(encoding="utf-8"))
    rates = {k.upper(): Decimal(str(v)) for k, v in data.get("rates", {}).items()}
    base = str(data.get("base", "USD")).upper()
    return base, rates


def _rate_for(currency: str, overrides: dict[str, object] | None) -> Decimal:
    ccy = (currency or "").strip().upper()
    if not ccy:
        raise UnknownCurrency("empty currency")
    if overrides:
        # Allow case-insensitive override keys.
        for k, v in overrides.items():
            if str(k).strip().upper() == ccy:
                return Decimal(str(v))
    _, rates = _load()
    if ccy not in rates:
        raise UnknownCurrency(ccy)
    return rates[ccy]


def convert(
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    overrides: dict[str, object] | None = None,
) -> Decimal:
    """Convert `amount` from one currency to another using base-relative rates.

    rate[C] is units of C per 1 unit of base, so:
        amount_base = amount / rate[from]
        result      = amount_base * rate[to]
    """
    if amount is None:
        raise ValueError("amount is required")
    src = (from_currency or "").strip().upper()
    dst = (to_currency or "").strip().upper()
    if src == dst:
        return Decimal(amount)
    rate_from = _rate_for(src, overrides)
    rate_to = _rate_for(dst, overrides)
    if rate_from == 0:
        raise UnknownCurrency(src)
    return (Decimal(amount) / rate_from) * rate_to


def known_currencies() -> list[str]:
    _, rates = _load()
    return sorted(rates.keys())
