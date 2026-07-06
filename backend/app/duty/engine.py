"""Pure Pakistan duty/tax stack arithmetic. No I/O, exhaustively unit-tested.

Compounding order (legally significant -- see the SRO/Act references carried
on each `LevyLine`; this module only implements the sequencing, it does not
decide the rates):

    assessed_value_pkr = declared_value_usd * exchange_rate
    CD  = assessed_value * cd_rate
    ACD = assessed_value * acd_rate
    RD  = assessed_value * rd_rate
    FED = assessed_value * fed_rate
    value_for_st  = assessed_value + CD + ACD + RD + FED
    ST  = value_for_st * st_rate
    value_for_wht = value_for_st + ST
    WHT = value_for_wht * wht_rate
    total_duty_tax = CD + ACD + RD + FED + ST + WHT
    total_landed   = assessed_value + total_duty_tax

All inputs are coerced to `Decimal` for exact arithmetic. Percentages are
fractions (0.20 == 20%), matching the convention in `app.matrix.landed_cost`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.matrix.landed_cost import to_decimal

#: Order in which levies are compounded (also the display order).
LEVY_ORDER = ("CD", "ACD", "RD", "FED", "ST", "WHT_148")

_LEVY_LABELS = {
    "CD": "Customs Duty",
    "ACD": "Additional Customs Duty",
    "RD": "Regulatory Duty",
    "FED": "Federal Excise Duty",
    "ST": "Sales Tax",
    "WHT_148": "Advance Income Tax (Section 148)",
}


@dataclass
class LevyLine:
    """One row of the breakdown: a single levy applied (or not) at one rate."""

    levy_type: str
    label: str
    rate: Decimal
    rate_type: str
    basis_pkr: Decimal
    amount_pkr: Decimal
    legal_reference: str | None = None
    sro_reference: str | None = None
    exemption_applied: bool = False
    notes: str | None = None


@dataclass
class DutyBreakdown:
    """Full result of a duty/tax calculation for one line item."""

    hs_code: str
    declared_value_usd: Decimal
    exchange_rate: Decimal
    assessed_value_pkr: Decimal
    importer_category: str | None
    atl_status: str | None
    as_of_date: date
    lines: list[LevyLine] = field(default_factory=list)
    total_duty_tax_pkr: Decimal = Decimal(0)
    total_landed_pkr: Decimal = Decimal(0)

    def line(self, levy_type: str) -> LevyLine | None:
        return next((l for l in self.lines if l.levy_type == levy_type), None)


def compute_duty_stack(
    *,
    hs_code: str,
    declared_value_usd: Decimal | float | int | str,
    exchange_rate: Decimal | float | int | str,
    cd_rate: Decimal | float | int | str = 0,
    acd_rate: Decimal | float | int | str = 0,
    rd_rate: Decimal | float | int | str = 0,
    fed_rate: Decimal | float | int | str = 0,
    st_rate: Decimal | float | int | str = 0,
    wht_rate: Decimal | float | int | str = 0,
    importer_category: str | None = None,
    atl_status: str | None = None,
    as_of_date: date | None = None,
    references: dict[str, dict] | None = None,
) -> DutyBreakdown:
    """Compound the five-levy Pakistan import duty/tax stack.

    `references` optionally carries per-levy metadata (legal_reference,
    sro_reference, notes, exemption_applied) so callers (the DB-backed
    resolver) can attach citations without this function doing any I/O
    itself.
    """
    declared_value = to_decimal(declared_value_usd)
    rate = to_decimal(exchange_rate)
    if declared_value is None or rate is None:
        raise ValueError("declared_value_usd and exchange_rate are required")
    if declared_value < 0:
        raise ValueError("declared_value_usd must be >= 0")
    if rate <= 0:
        raise ValueError("exchange_rate must be > 0")

    refs = references or {}

    def _ref(levy: str) -> dict:
        return refs.get(levy, {})

    assessed_value = declared_value * rate

    cd_r = to_decimal(cd_rate, Decimal(0)) or Decimal(0)
    acd_r = to_decimal(acd_rate, Decimal(0)) or Decimal(0)
    rd_r = to_decimal(rd_rate, Decimal(0)) or Decimal(0)
    fed_r = to_decimal(fed_rate, Decimal(0)) or Decimal(0)
    st_r = to_decimal(st_rate, Decimal(0)) or Decimal(0)
    wht_r = to_decimal(wht_rate, Decimal(0)) or Decimal(0)

    cd_amount = assessed_value * cd_r
    acd_amount = assessed_value * acd_r
    rd_amount = assessed_value * rd_r
    fed_amount = assessed_value * fed_r

    value_for_st = assessed_value + cd_amount + acd_amount + rd_amount + fed_amount
    st_amount = value_for_st * st_r

    value_for_wht = value_for_st + st_amount
    wht_amount = value_for_wht * wht_r

    total_duty_tax = (
        cd_amount + acd_amount + rd_amount + fed_amount + st_amount + wht_amount
    )
    total_landed = assessed_value + total_duty_tax

    rates_and_bases = {
        "CD": (cd_r, assessed_value, cd_amount),
        "ACD": (acd_r, assessed_value, acd_amount),
        "RD": (rd_r, assessed_value, rd_amount),
        "FED": (fed_r, assessed_value, fed_amount),
        "ST": (st_r, value_for_st, st_amount),
        "WHT_148": (wht_r, value_for_wht, wht_amount),
    }

    lines = []
    for levy in LEVY_ORDER:
        r = _ref(levy)
        levy_rate, basis, amount = rates_and_bases[levy]
        lines.append(
            LevyLine(
                levy_type=levy,
                label=_LEVY_LABELS[levy],
                rate=levy_rate,
                rate_type=r.get("rate_type", "percent"),
                basis_pkr=basis,
                amount_pkr=amount,
                legal_reference=r.get("legal_reference"),
                sro_reference=r.get("sro_reference"),
                exemption_applied=bool(r.get("exemption_applied", False)),
                notes=r.get("notes"),
            )
        )

    return DutyBreakdown(
        hs_code=hs_code,
        declared_value_usd=declared_value,
        exchange_rate=rate,
        assessed_value_pkr=assessed_value,
        importer_category=importer_category,
        atl_status=atl_status,
        as_of_date=as_of_date or date.today(),
        lines=lines,
        total_duty_tax_pkr=total_duty_tax,
        total_landed_pkr=total_landed,
    )
