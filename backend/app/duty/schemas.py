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

from pydantic import BaseModel, ConfigDict, Field, model_validator

LevyType = Literal["CD", "ACD", "RD", "ST", "FED", "WHT_148"]
#: Sheet-style breakdown levy set (invoice calculator); AST is the sheet's
#: Additional Sales Tax, AIT its Advance Income Tax line, FED a manual amount.
SheetLevyType = Literal["CD", "ACD", "RD", "ST", "AST", "FED", "AIT"]
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


PARSE_DISCLAIMER = (
    "AI-extracted line items -- review descriptions, quantities and prices "
    "against the source document before calculating."
)


class InvoiceItemParsed(BaseModel):
    """One line item extracted from an invoice/quotation by the LLM."""

    line_no: int | None = None
    description: str
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None


class InvoiceParseOut(BaseModel):
    """Response for `POST /duty-calc/invoice/parse`."""

    invoice_currency: str | None = None
    freight: Decimal = Decimal(0)
    items: list[InvoiceItemParsed]
    disclaimer: str = PARSE_DISCLAIMER


class ItemRatesIn(BaseModel):
    """Per-item sheet rates as fractions (0.05 == 5%)."""

    cd: Decimal = Field(ge=0, le=1)
    acd: Decimal = Field(ge=0, le=1)
    rd: Decimal = Field(ge=0, le=1)
    st: Decimal = Field(ge=0, le=1)
    ast: Decimal = Field(ge=0, le=1)
    ait: Decimal = Field(ge=0, le=1)


class InvoiceCalcItemIn(BaseModel):
    """One line item of a `POST /duty-calc/invoice/calculate` request."""

    description: str = ""
    quantity: Decimal | None = Field(None, ge=0)
    unit: str | None = None
    unit_price: Decimal | None = Field(None, ge=0)
    line_total: Decimal | None = Field(None, ge=0)
    hs_code: str = Field(min_length=1)
    rates: ItemRatesIn
    fed_amount_pkr: Decimal = Field(Decimal(0), ge=0)

    @model_validator(mode="after")
    def _resolve_line_total(self) -> "InvoiceCalcItemIn":
        if self.line_total is None:
            if self.quantity is None or self.unit_price is None:
                raise ValueError(
                    "Provide line_total, or both quantity and unit_price."
                )
            self.line_total = self.quantity * self.unit_price
        return self


class InvoiceFeesIn(BaseModel):
    """The sheet's fixed/other payables block, editable per calculation."""

    afu_pct: Decimal = Field(Decimal("0.008"), ge=0, le=1)
    afu_fixed_pkr: Decimal = Field(Decimal(3), ge=0)
    stamp_fee_pkr: Decimal = Field(Decimal(2000), ge=0)
    psw_fee_pkr: Decimal = Field(Decimal(1000), ge=0)


class InvoiceCalcIn(BaseModel):
    """Request body for `POST /duty-calc/invoice/calculate` (pure math)."""

    currency: Literal["USD", "CNY"]
    fx_rate: Decimal = Field(gt=0, description="PKR per 1 unit of currency")
    fx_rate_date: date | None = None
    freight: Decimal = Field(Decimal(0), ge=0)
    insurance_pct: Decimal = Field(Decimal("0.01"), ge=0, le=1)
    landing_pct: Decimal = Field(Decimal("0.01"), ge=0, le=1)
    items: list[InvoiceCalcItemIn] = Field(min_length=1, max_length=50)
    fees: InvoiceFeesIn = Field(default_factory=InvoiceFeesIn)
    #: Persist each item's confirmed rates to `hs_rate_memory` for prefill.
    save_rates: bool = True


class SheetLevyLineOut(BaseModel):
    """One levy row of the sheet-style breakdown."""

    levy_type: SheetLevyType
    label: str
    rate: Decimal
    basis_pkr: Decimal
    amount_pkr: Decimal


class InvoiceCalcItemOut(BaseModel):
    """Sheet-style breakdown for one line item."""

    description: str
    hs_code: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    line_total: Decimal
    freight_allocated: Decimal
    cf_value: Decimal
    cf_value_pkr: Decimal
    insurance_pkr: Decimal
    landing_pkr: Decimal
    import_value_pkr: Decimal
    levies: list[SheetLevyLineOut]
    customs_subtotal_pkr: Decimal
    ait_pkr: Decimal
    item_duty_total_pkr: Decimal


class InvoiceTotalsOut(BaseModel):
    """Invoice-level totals incl. the sheet's fixed-fee block."""

    invoice_value: Decimal
    freight: Decimal
    cf_value_pkr: Decimal
    import_value_pkr: Decimal
    customs_subtotal_pkr: Decimal
    ait_pkr: Decimal
    customs_total_pkr: Decimal
    afu_pkr: Decimal
    stamp_fee_pkr: Decimal
    psw_fee_pkr: Decimal
    total_payable_pkr: Decimal
    landed_cleared_price_pkr: Decimal


class InvoiceCalcOut(BaseModel):
    """Response for `POST /duty-calc/invoice/calculate`."""

    currency: str
    fx_rate: Decimal
    fx_rate_date: date | None = None
    items: list[InvoiceCalcItemOut]
    totals: InvoiceTotalsOut
    disclaimer: str = DISCLAIMER


RateSource = Literal["memory", "approved_rate", "default"]


class RatePrefillOut(BaseModel):
    """Response for `GET /duty-calc/rate-prefill/{hs_code}`."""

    hs_code: str
    rates: dict[str, Decimal]
    sources: dict[str, RateSource]


class FxRateOut(BaseModel):
    """Response for `GET /duty-calc/fx-rate`."""

    currency: str
    quote: str = "PKR"
    rate: Decimal
    as_of_date: date
    source: Literal["live", "static"]


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
