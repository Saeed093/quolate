"""Live PKR exchange rates for the duty calculator, with static fallback.

One keyless upstream call (open.er-api.com, USD-base table) covers both
USD->PKR and CNY->PKR (cross rate), cached per calendar day per process.
Any failure falls back to the bundled static table in `app.matrix.fx` --
the caller surfaces `source` so the UI can flag "offline table rate, verify".

Note the live rate is the open-market rate, not FBR's customs-notified
weekly rate -- which is why every consumer keeps it user-overridable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

import httpx

from app.matrix.fx import convert

_ER_API_URL = "https://open.er-api.com/v6/latest/USD"
_FETCH_TIMEOUT_SECONDS = 5.0

#: {calendar day: USD-base rates table} -- at most one upstream call per day.
_CACHE: dict[date, dict[str, Decimal]] = {}


@dataclass
class FxRate:
    currency: str
    rate: Decimal  # PKR per 1 unit of `currency`
    as_of_date: date
    source: Literal["live", "static"]


async def _fetch_usd_table() -> dict[str, Decimal]:
    """Fetch the USD-base rates table. Split out so tests can monkeypatch."""
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS) as client:
        resp = await client.get(_ER_API_URL)
        resp.raise_for_status()
        data = resp.json()
    if data.get("result") != "success":
        raise ValueError(f"FX API returned {data.get('result')!r}")
    return {
        code.upper(): Decimal(str(value))
        for code, value in (data.get("rates") or {}).items()
    }


async def get_pkr_rate(currency: str) -> FxRate:
    """PKR per one unit of `currency` (USD or CNY), live if possible."""
    return await get_live_rate(currency, "PKR")


async def get_live_rate(base: str, quote: str) -> FxRate:
    """`quote` units per 1 unit of `base`, live if possible, static fallback.

    Generalises `get_pkr_rate` to any currency pair. The upstream table is
    USD-based, so cross rates are derived (table[quote] / table[base]).
    """
    b = (base or "").strip().upper()
    q = (quote or "").strip().upper()
    today = date.today()
    try:
        table = _CACHE.get(today)
        if table is None:
            table = await _fetch_usd_table()
            _CACHE.clear()
            _CACHE[today] = table
        # table[X] is units of X per 1 USD.
        base_per_usd = Decimal(1) if b == "USD" else table[b]
        quote_per_usd = Decimal(1) if q == "USD" else table[q]
        rate = quote_per_usd / base_per_usd
        return FxRate(currency=q, rate=rate, as_of_date=today, source="live")
    except Exception:
        return FxRate(
            currency=q,
            rate=convert(Decimal(1), b, q),
            as_of_date=today,
            source="static",
        )
