"""Pydantic models for the Pakistan duty/tax calculation engine.

Kept separate from the root `app.schemas` module (rather than folded in)
because this domain has enough shape of its own -- levy/rate-type enums,
the rate-row/exemption-row shapes mirroring the DB tables, and the
slab-rule shape -- to warrant its own file; it will also become the
validation target for the LLM-assisted SRO extraction step (a future
session).
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

LevyType = Literal["CD", "ACD", "RD", "ST", "FED", "WHT_148"]
RateType = Literal["percent", "fixed", "slab"]
AtlStatus = Literal["atl", "non_atl"]
RowStatus = Literal["pending_review", "approved", "rejected"]
ExemptionType = Literal["full", "reduced_rate"]

DISCLAIMER = (
    "This is a calculation aid based on ingested rate data as of the "
    "requested date. It is not a substitute for the actual statute/SRO text "
    "or a customs agent's WeBOC-assessed figure -- verify before relying on "
    "this for a client-facing quote or a filing."
)


class LevyLineOut(BaseModel):
    """One row of the breakdown returned by the calculator."""

    levy_type: LevyType
    label: str
    rate: Decimal
    rate_type: str
    basis_pkr: Decimal
    amount_pkr: Decimal
    legal_reference: str | None = None
    sro_reference: str | None = None
    exemption_applied: bool = False
    notes: str | None = None


class DutyCalculationOut(BaseModel):
    """Full response for `GET /duty-calc/{hs_code}`."""

    hs_code: str
    declared_value_usd: Decimal
    exchange_rate: Decimal
    assessed_value_pkr: Decimal
    importer_category: str | None = None
    atl_status: AtlStatus | None = None
    as_of_date: date
    levies: list[LevyLineOut]
    total_duty_tax_pkr: Decimal
    total_landed_pkr: Decimal
    disclaimer: str = DISCLAIMER


class SlabRule(BaseModel):
    """One bracket of an ACD/RD slab schedule, keyed on the CD ad-valorem rate.

    e.g. {"cd_rate_min": 0, "cd_rate_max": 0.10, "rate": 0.02} means "if CD is
    between 0% and 10% inclusive, ACD = 2%".
    """

    cd_rate_min: Decimal
    cd_rate_max: Decimal | None = None
    rate: Decimal
    sro_reference: str | None = None
    legal_reference: str | None = None
    notes: str | None = None


class DutyTaxRateOut(BaseModel):
    """Mirrors a `duty_tax_rates` row (admin review / future ingestion UI)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hs_code: str
    levy_type: LevyType
    rate_type: RateType
    rate_value: Decimal | None
    slab_rules: list[SlabRule] | None = None
    importer_category: str | None
    atl_status: AtlStatus | None
    sro_reference: str | None
    legal_reference: str | None
    effective_from: date
    effective_to: date | None
    superseded_by: uuid.UUID | None = None
    status: RowStatus
    source_document: str | None = None
    notes: str | None


CLASSIFY_DISCLAIMER = (
    "AI-suggested classification, not a customs ruling -- verify the HS code "
    "against the actual tariff schedule (or with a customs agent) before "
    "relying on it for a filing or a client-facing quote."
)


class HsCandidate(BaseModel):
    """One ranked HS/PCT code suggestion from the classifier."""

    hs_code: str
    description: str | None = None
    confidence: float
    reasoning: str | None = None


class HsClassificationOut(BaseModel):
    """Response for `POST /duty-calc/classify` and the `classify_hs_code` chat tool."""

    product_summary: str | None = None
    candidates: list[HsCandidate]
    disclaimer: str = CLASSIFY_DISCLAIMER


class ExemptionRuleOut(BaseModel):
    """Mirrors an `exemption_rules` row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hs_code: str | None
    levy_type: LevyType
    importer_category: str | None
    certificate_type: str | None
    requires_certificate: bool
    exemption_type: ExemptionType
    reduced_rate: Decimal | None
    condition_description: str | None
    sro_reference: str | None
    schedule_reference: str | None
    effective_from: date
    effective_to: date | None
    status: RowStatus
    source_document: str | None = None
    notes: str | None
