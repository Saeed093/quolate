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
    ccy = (currency or "").strip().upper()
    today = date.today()
    try:
        table = _CACHE.get(today)
        if table is None:
            table = await _fetch_usd_table()
            _CACHE.clear()
            _CACHE[today] = table
        pkr_per_usd = table["PKR"]
        if ccy == "USD":
            rate = pkr_per_usd
        else:
            rate = pkr_per_usd / table[ccy]
        return FxRate(currency=ccy, rate=rate, as_of_date=today, source="live")
    except Exception:
        return FxRate(
            currency=ccy,
            rate=convert(Decimal(1), ccy, "PKR"),
            as_of_date=today,
            source="static",
        )
