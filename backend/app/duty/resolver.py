"""DB-backed rate & exemption resolution for the Pakistan duty engine.

Keeps all Postgres access isolated from `app.duty.engine` (pure math) so the
compounding formula stays trivially unit-testable. This module decides,
*as of a given date*, which rate row applies for each levy -- including the
ACD/RD slab logic and the importer-category/certificate exemption checks --
and hands plain Decimals + citations back to the engine.

Resolution rules (spec section 1 & "constraints" section):
  - `hs_code == "*"` is the wildcard row: a schedule that isn't keyed by HS
    code at all (the standard ST rate, an ACD/RD slab schedule keyed on the
    CD bracket, or a general WHT-148 rate).
  - CD/RD/FED never fall back to the wildcard: with no HS-specific row they
    are 0 (RD in particular is "applied only to specific flagged PCT
    codes" -- spec section "why this is hard", point 3).
  - ACD prefers an HS-specific override row; failing that, it falls back to
    the general CD-rate-bracket slab schedule.
  - ST/WHT_148 first check `exemption_rules` (importer-category/certificate
    conditional), then fall back to an HS-specific `duty_tax_rates` row
    (e.g. Sixth/Eighth Schedule treatment), then the wildcard/general row.
  - Among candidate rows, the most specific one wins: exact HS code beats
    the wildcard, an exact importer_category/atl_status match beats a NULL
    (general) row.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DutyTaxRate, ExemptionRule
from app.matrix.landed_cost import to_decimal

#: Wildcard HS code for rows not keyed by a specific HS code.
GENERAL_HS_CODE = "*"

_HS_LEVIES_REQUIRING_EXACT_MATCH = ("CD", "RD", "FED")


@dataclass
class ResolvedLevy:
    """One levy's resolved rate + the citation to show in the breakdown."""

    rate: Decimal
    rate_type: str = "percent"
    legal_reference: str | None = None
    sro_reference: str | None = None
    exemption_applied: bool = False
    notes: str | None = None
    source_row_id: str | None = None

    def as_reference(self) -> dict:
        return {
            "rate_type": self.rate_type,
            "legal_reference": self.legal_reference,
            "sro_reference": self.sro_reference,
            "exemption_applied": self.exemption_applied,
            "notes": self.notes,
        }


async def _active_rate_rows(
    session: AsyncSession,
    *,
    hs_code: str,
    levy_type: str,
    as_of_date: date,
    allow_wildcard: bool = True,
) -> list[DutyTaxRate]:
    hs_candidates = [hs_code, GENERAL_HS_CODE] if allow_wildcard else [hs_code]
    result = await session.execute(
        select(DutyTaxRate).where(
            DutyTaxRate.hs_code.in_(hs_candidates),
            DutyTaxRate.levy_type == levy_type,
            DutyTaxRate.status == "approved",
            DutyTaxRate.effective_from <= as_of_date,
            (DutyTaxRate.effective_to.is_(None))
            | (DutyTaxRate.effective_to >= as_of_date),
        )
    )
    return list(result.scalars().all())


def _best_rate_match(
    rows: list[DutyTaxRate],
    *,
    hs_code: str,
    importer_category: str | None,
    atl_status: str | None,
) -> DutyTaxRate | None:
    """Most-specific-wins among rows whose conditions are satisfied.

    A row is a *candidate* only if its importer_category/atl_status are
    either NULL (general -- always satisfied) or an exact match of what the
    caller supplied. Among candidates, prefer exact HS code over wildcard,
    then exact importer_category match, then exact atl_status match.
    """
    candidates = [
        row
        for row in rows
        if row.importer_category in (None, importer_category)
        and row.atl_status in (None, atl_status)
    ]
    if not candidates:
        return None

    def score(row: DutyTaxRate) -> tuple[int, int, int]:
        return (
            1 if row.hs_code == hs_code else 0,
            1 if row.importer_category is not None else 0,
            1 if row.atl_status is not None else 0,
        )

    return max(candidates, key=score)


def _resolve_slab_rate(row: DutyTaxRate, basis_rate: Decimal) -> ResolvedLevy:
    """Pick the bracket in `row.slab_rules` whose [min, max] contains `basis_rate`."""
    for bracket in row.slab_rules or []:
        lo = to_decimal(bracket.get("cd_rate_min", 0), Decimal(0))
        hi_raw = bracket.get("cd_rate_max")
        hi = to_decimal(hi_raw) if hi_raw is not None else None
        if basis_rate >= lo and (hi is None or basis_rate <= hi):
            return ResolvedLevy(
                rate=to_decimal(bracket.get("rate"), Decimal(0)) or Decimal(0),
                legal_reference=bracket.get("legal_reference") or row.legal_reference,
                sro_reference=bracket.get("sro_reference") or row.sro_reference,
                notes=bracket.get("notes")
                or "Resolved via slab schedule bracket based on the CD rate.",
                source_row_id=str(row.id),
            )
    return ResolvedLevy(
        rate=Decimal(0),
        notes="No matching bracket in the slab schedule for this CD rate.",
        source_row_id=str(row.id),
    )


async def _active_exemptions(
    session: AsyncSession,
    *,
    hs_code: str,
    levy_type: str,
    importer_category: str | None,
    as_of_date: date,
) -> list[ExemptionRule]:
    result = await session.execute(
        select(ExemptionRule).where(
            ExemptionRule.levy_type == levy_type,
            ExemptionRule.status == "approved",
            ExemptionRule.effective_from <= as_of_date,
            (ExemptionRule.effective_to.is_(None))
            | (ExemptionRule.effective_to >= as_of_date),
            (ExemptionRule.hs_code.is_(None)) | (ExemptionRule.hs_code == hs_code),
            (ExemptionRule.importer_category.is_(None))
            | (ExemptionRule.importer_category == importer_category),
        )
    )
    return list(result.scalars().all())


def _best_exemption_match(
    rows: list[ExemptionRule], *, hs_code: str, importer_category: str | None
) -> ExemptionRule | None:
    if not rows:
        return None

    def score(row: ExemptionRule) -> tuple[int, int]:
        return (
            1 if row.hs_code == hs_code else 0,
            1 if row.importer_category is not None else 0,
        )

    return max(rows, key=score)


def _exemption_to_resolved(exemption: ExemptionRule) -> ResolvedLevy:
    rate = Decimal(0)
    if exemption.exemption_type == "reduced_rate":
        rate = to_decimal(exemption.reduced_rate, Decimal(0)) or Decimal(0)
    note_bits = [exemption.condition_description or "Conditional exemption applied."]
    if exemption.requires_certificate:
        note_bits.append(
            f"Requires certificate: {exemption.certificate_type or 'see SRO'}."
        )
    return ResolvedLevy(
        rate=rate,
        legal_reference=exemption.schedule_reference,
        sro_reference=exemption.sro_reference,
        exemption_applied=True,
        notes=" ".join(note_bits),
        source_row_id=str(exemption.id),
    )


async def _resolve_direct(
    session: AsyncSession,
    *,
    hs_code: str,
    levy_type: str,
    importer_category: str | None,
    atl_status: str | None,
    as_of_date: date,
    allow_wildcard: bool,
    not_found_note: str,
) -> ResolvedLevy:
    rows = await _active_rate_rows(
        session,
        hs_code=hs_code,
        levy_type=levy_type,
        as_of_date=as_of_date,
        allow_wildcard=allow_wildcard,
    )
    row = _best_rate_match(
        rows, hs_code=hs_code, importer_category=importer_category, atl_status=atl_status
    )
    if row is None:
        return ResolvedLevy(rate=Decimal(0), notes=not_found_note)
    return ResolvedLevy(
        rate=to_decimal(row.rate_value, Decimal(0)) or Decimal(0),
        rate_type=row.rate_type,
        legal_reference=row.legal_reference,
        sro_reference=row.sro_reference,
        notes=row.notes,
        source_row_id=str(row.id),
    )


async def _resolve_acd(
    session: AsyncSession,
    *,
    hs_code: str,
    importer_category: str | None,
    atl_status: str | None,
    as_of_date: date,
    cd_rate: Decimal,
) -> ResolvedLevy:
    # 1. HS-specific ACD override row (some ACD SROs do flag specific PCT
    #    codes directly rather than relying purely on the CD-rate slab).
    specific_rows = await _active_rate_rows(
        session,
        hs_code=hs_code,
        levy_type="ACD",
        as_of_date=as_of_date,
        allow_wildcard=False,
    )
    specific_row = _best_rate_match(
        specific_rows,
        hs_code=hs_code,
        importer_category=importer_category,
        atl_status=atl_status,
    )
    if specific_row is not None and specific_row.rate_type != "slab":
        return ResolvedLevy(
            rate=to_decimal(specific_row.rate_value, Decimal(0)) or Decimal(0),
            rate_type=specific_row.rate_type,
            legal_reference=specific_row.legal_reference,
            sro_reference=specific_row.sro_reference,
            notes=specific_row.notes,
            source_row_id=str(specific_row.id),
        )

    # 2. Fall back to the general CD-rate-bracket slab schedule.
    slab_rows = [
        row
        for row in await _active_rate_rows(
            session,
            hs_code=GENERAL_HS_CODE,
            levy_type="ACD",
            as_of_date=as_of_date,
            allow_wildcard=False,
        )
        if row.rate_type == "slab"
    ]
    slab_row = _best_rate_match(
        slab_rows,
        hs_code=GENERAL_HS_CODE,
        importer_category=importer_category,
        atl_status=atl_status,
    )
    if slab_row is not None:
        return _resolve_slab_rate(slab_row, cd_rate)

    return ResolvedLevy(rate=Decimal(0), notes="No ACD row or slab schedule found.")


async def _resolve_with_exemption(
    session: AsyncSession,
    *,
    hs_code: str,
    levy_type: str,
    importer_category: str | None,
    atl_status: str | None,
    as_of_date: date,
) -> ResolvedLevy:
    exemptions = await _active_exemptions(
        session,
        hs_code=hs_code,
        levy_type=levy_type,
        importer_category=importer_category,
        as_of_date=as_of_date,
    )
    exemption = _best_exemption_match(
        exemptions, hs_code=hs_code, importer_category=importer_category
    )
    if exemption is not None:
        return _exemption_to_resolved(exemption)

    return await _resolve_direct(
        session,
        hs_code=hs_code,
        levy_type=levy_type,
        importer_category=importer_category,
        atl_status=atl_status,
        as_of_date=as_of_date,
        allow_wildcard=True,
        not_found_note=f"No {levy_type} rate configured for this HS code as of {as_of_date}.",
    )


async def resolve_rates(
    session: AsyncSession,
    *,
    hs_code: str,
    importer_category: str | None,
    atl_status: str | None,
    as_of_date: date,
) -> dict[str, ResolvedLevy]:
    """Resolve every levy for one HS code as of one date.

    Returns a dict keyed by levy type (`CD`, `ACD`, `RD`, `FED`, `ST`,
    `WHT_148`), each a `ResolvedLevy` with the rate plus the legal/SRO
    citation to surface in the breakdown.
    """
    resolved: dict[str, ResolvedLevy] = {}

    for levy in _HS_LEVIES_REQUIRING_EXACT_MATCH:  # CD, RD, FED
        resolved[levy] = await _resolve_direct(
            session,
            hs_code=hs_code,
            levy_type=levy,
            importer_category=importer_category,
            atl_status=atl_status,
            as_of_date=as_of_date,
            allow_wildcard=False,
            not_found_note=f"No {levy} row for this HS code as of {as_of_date} -- assumed 0%.",
        )

    resolved["ACD"] = await _resolve_acd(
        session,
        hs_code=hs_code,
        importer_category=importer_category,
        atl_status=atl_status,
        as_of_date=as_of_date,
        cd_rate=resolved["CD"].rate,
    )

    resolved["ST"] = await _resolve_with_exemption(
        session,
        hs_code=hs_code,
        levy_type="ST",
        importer_category=importer_category,
        atl_status=atl_status,
        as_of_date=as_of_date,
    )

    resolved["WHT_148"] = await _resolve_with_exemption(
        session,
        hs_code=hs_code,
        levy_type="WHT_148",
        importer_category=importer_category,
        atl_status=atl_status,
        as_of_date=as_of_date,
    )

    return resolved
