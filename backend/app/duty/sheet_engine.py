"""Pure arithmetic for the clearing-agent "Duty Calculation Sheet" workflow.

Reproduces the user's authoritative Excel sheet exactly (see the duty
calculator plan; formulas transcribed cell-by-cell from the workbook), which
differs structurally from `app.duty.engine.compute_duty_stack`:

    cf        = line_total + freight_allocated        (invoice currency)
    cf_pkr    = cf * fx_rate
    insurance = cf_pkr * insurance_pct                 ("1% OR AS PER MEMO")
    landing   = (cf_pkr + insurance) * landing_pct
    IV        = cf_pkr + insurance + landing           ("IMPORT VALUE")
    CD  = IV * cd        ACD = IV * acd       RD = IV * rd
    ST  = (IV + CD + ACD + RD) * st                    -- FED NOT in the base
    AST = (CD + ACD + RD) * ast                        -- the sheet's base
    FED = manual PKR amount ("FED/Fine (If applicable)")
    SUBTOTAL = CD + ACD + RD + ST + AST + FED
    AIT = (IV + SUBTOTAL) * ait
    item_customs_total = SUBTOTAL + AIT                ("TOTAL PAYABLE")

Invoice level, on top of the per-item sums:

    AFU = IV_total * afu_pct + afu_fixed               (Excise & Taxation AFU)
    total_payable = customs_total + AFU + stamp + psw  ("Total Payable Amount")
    landed_cleared = cf_pkr_total + total_payable

Insurance and landing charges are customs *valuation* constructs (they inflate
the duty base), not cash costs, so they are deliberately absent from the
landed-cleared price. All math is `Decimal` at full precision -- rounding is
display-only, so totals can differ from the sheet's rounded cells by <1 PKR.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.matrix.landed_cost import to_decimal

#: Compounding/display order for the sheet-style breakdown.
SHEET_LEVY_ORDER = ("CD", "ACD", "RD", "ST", "AST", "FED", "AIT")

SHEET_LEVY_LABELS = {
    "CD": "Customs Duty",
    "ACD": "Additional Customs Duty",
    "RD": "Regulatory Duty",
    "ST": "Sales Tax",
    "AST": "Additional Sales Tax",
    "FED": "FED / Fine (manual)",
    "AIT": "Advance Income Tax",
}

#: The sheet's sample rates -- the prefill of last resort (fractions).
SHEET_DEFAULT_RATES = {
    "cd": Decimal("0.05"),
    "acd": Decimal("0.02"),
    "rd": Decimal("0.15"),
    "st": Decimal("0.18"),
    "ast": Decimal("0.03"),
    "ait": Decimal("0.055"),
}

DEFAULT_INSURANCE_PCT = Decimal("0.01")
DEFAULT_LANDING_PCT = Decimal("0.01")

#: Fixed/other payables from the sheet's top summary block.
DEFAULT_AFU_PCT = Decimal("0.008")  # Excise & Taxation AFU: IV * 0.8% + 3
DEFAULT_AFU_FIXED_PKR = Decimal("3")
DEFAULT_STAMP_FEE_PKR = Decimal("2000")  # Assistant Superintendent of Stamps
DEFAULT_PSW_FEE_PKR = Decimal("1000")  # Payment Against PSW GD Fee


@dataclass
class SheetLevyLine:
    """One levy row of the sheet-style breakdown."""

    levy_type: str
    label: str
    rate: Decimal
    basis_pkr: Decimal
    amount_pkr: Decimal


@dataclass
class ItemSheetBreakdown:
    """Full sheet-style duty stack for one invoice line item."""

    description: str
    hs_code: str
    quantity: Decimal | None
    unit_price: Decimal | None
    line_total: Decimal
    freight_allocated: Decimal
    cf_value: Decimal
    cf_value_pkr: Decimal
    insurance_pkr: Decimal
    landing_pkr: Decimal
    import_value_pkr: Decimal
    lines: list[SheetLevyLine] = field(default_factory=list)
    customs_subtotal_pkr: Decimal = Decimal(0)
    ait_pkr: Decimal = Decimal(0)
    item_duty_total_pkr: Decimal = Decimal(0)

    def line(self, levy_type: str) -> SheetLevyLine | None:
        return next((l for l in self.lines if l.levy_type == levy_type), None)


@dataclass
class InvoiceSheetBreakdown:
    """Per-item breakdowns plus the invoice-level fee/total block."""

    currency: str
    fx_rate: Decimal
    items: list[ItemSheetBreakdown]
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


def compute_item_sheet_duty(
    *,
    description: str,
    hs_code: str,
    line_total: Decimal | float | int | str,
    freight_allocated: Decimal | float | int | str = 0,
    fx_rate: Decimal | float | int | str,
    insurance_pct: Decimal | float | int | str = DEFAULT_INSURANCE_PCT,
    landing_pct: Decimal | float | int | str = DEFAULT_LANDING_PCT,
    rates: dict[str, Decimal | float | int | str] | None = None,
    fed_amount_pkr: Decimal | float | int | str = 0,
    quantity: Decimal | None = None,
    unit_price: Decimal | None = None,
) -> ItemSheetBreakdown:
    """Compute the sheet's duty stack for one line item.

    `rates` holds fractions keyed cd/acd/rd/st/ast/ait; missing keys fall back
    to `SHEET_DEFAULT_RATES`. `fed_amount_pkr` is a manual PKR amount, not a
    rate (the sheet's "FED/Fine (If applicable)" cell).
    """
    total = to_decimal(line_total)
    fx = to_decimal(fx_rate)
    if total is None or fx is None:
        raise ValueError("line_total and fx_rate are required")
    if total < 0:
        raise ValueError("line_total must be >= 0")
    if fx <= 0:
        raise ValueError("fx_rate must be > 0")

    freight = to_decimal(freight_allocated, Decimal(0)) or Decimal(0)
    ins_pct = to_decimal(insurance_pct, DEFAULT_INSURANCE_PCT) or Decimal(0)
    land_pct = to_decimal(landing_pct, DEFAULT_LANDING_PCT) or Decimal(0)
    fed = to_decimal(fed_amount_pkr, Decimal(0)) or Decimal(0)

    given = rates or {}

    def _rate(key: str) -> Decimal:
        value = to_decimal(given.get(key))
        return value if value is not None else SHEET_DEFAULT_RATES[key]

    cf = total + freight
    cf_pkr = cf * fx
    insurance = cf_pkr * ins_pct
    landing = (cf_pkr + insurance) * land_pct
    iv = cf_pkr + insurance + landing

    cd_r, acd_r, rd_r = _rate("cd"), _rate("acd"), _rate("rd")
    st_r, ast_r, ait_r = _rate("st"), _rate("ast"), _rate("ait")

    cd = iv * cd_r
    acd = iv * acd_r
    rd = iv * rd_r
    st_basis = iv + cd + acd + rd
    st = st_basis * st_r
    ast_basis = cd + acd + rd
    ast = ast_basis * ast_r

    subtotal = cd + acd + rd + st + ast + fed
    ait_basis = iv + subtotal
    ait = ait_basis * ait_r

    lines = [
        SheetLevyLine("CD", SHEET_LEVY_LABELS["CD"], cd_r, iv, cd),
        SheetLevyLine("ACD", SHEET_LEVY_LABELS["ACD"], acd_r, iv, acd),
        SheetLevyLine("RD", SHEET_LEVY_LABELS["RD"], rd_r, iv, rd),
        SheetLevyLine("ST", SHEET_LEVY_LABELS["ST"], st_r, st_basis, st),
        SheetLevyLine("AST", SHEET_LEVY_LABELS["AST"], ast_r, ast_basis, ast),
        SheetLevyLine("FED", SHEET_LEVY_LABELS["FED"], Decimal(0), Decimal(0), fed),
        SheetLevyLine("AIT", SHEET_LEVY_LABELS["AIT"], ait_r, ait_basis, ait),
    ]

    return ItemSheetBreakdown(
        description=description,
        hs_code=hs_code,
        quantity=quantity,
        unit_price=unit_price,
        line_total=total,
        freight_allocated=freight,
        cf_value=cf,
        cf_value_pkr=cf_pkr,
        insurance_pkr=insurance,
        landing_pkr=landing,
        import_value_pkr=iv,
        lines=lines,
        customs_subtotal_pkr=subtotal,
        ait_pkr=ait,
        item_duty_total_pkr=subtotal + ait,
    )


def allocate_freight(
    line_totals: list[Decimal], freight_total: Decimal
) -> list[Decimal]:
    """Pro-rata freight allocation by line value; equal split when all zero.

    The sheet works at whole-invoice level (one "Value Freight" cell), so a
    multi-item invoice needs the freight spread across items to keep each
    item's C&F -- and therefore its duty stack -- self-contained.
    """
    if not line_totals:
        return []
    if freight_total == 0:
        return [Decimal(0)] * len(line_totals)
    total = sum(line_totals, Decimal(0))
    if total == 0:
        share = freight_total / Decimal(len(line_totals))
        return [share] * len(line_totals)
    return [freight_total * lt / total for lt in line_totals]


def compute_invoice_sheet_duty(
    *,
    items: list[dict],
    currency: str,
    fx_rate: Decimal | float | int | str,
    freight: Decimal | float | int | str = 0,
    insurance_pct: Decimal | float | int | str = DEFAULT_INSURANCE_PCT,
    landing_pct: Decimal | float | int | str = DEFAULT_LANDING_PCT,
    afu_pct: Decimal | float | int | str = DEFAULT_AFU_PCT,
    afu_fixed_pkr: Decimal | float | int | str = DEFAULT_AFU_FIXED_PKR,
    stamp_fee_pkr: Decimal | float | int | str = DEFAULT_STAMP_FEE_PKR,
    psw_fee_pkr: Decimal | float | int | str = DEFAULT_PSW_FEE_PKR,
) -> InvoiceSheetBreakdown:
    """Compute the whole-invoice sheet: per-item stacks + the fee block.

    Each entry of `items` is a dict with description, hs_code, line_total and
    optionally quantity, unit_price, rates (fractions) and fed_amount_pkr --
    the shape the API layer hands over after Pydantic validation.
    """
    if not items:
        raise ValueError("at least one item is required")

    fx = to_decimal(fx_rate)
    if fx is None or fx <= 0:
        raise ValueError("fx_rate must be > 0")
    freight_total = to_decimal(freight, Decimal(0)) or Decimal(0)

    line_totals = [
        to_decimal(item.get("line_total"), Decimal(0)) or Decimal(0) for item in items
    ]
    allocations = allocate_freight(line_totals, freight_total)

    breakdowns = [
        compute_item_sheet_duty(
            description=item.get("description", ""),
            hs_code=item.get("hs_code", ""),
            line_total=line_total,
            freight_allocated=allocated,
            fx_rate=fx,
            insurance_pct=insurance_pct,
            landing_pct=landing_pct,
            rates=item.get("rates"),
            fed_amount_pkr=item.get("fed_amount_pkr", 0),
            quantity=to_decimal(item.get("quantity")),
            unit_price=to_decimal(item.get("unit_price")),
        )
        for item, line_total, allocated in zip(items, line_totals, allocations)
    ]

    iv_total = sum((b.import_value_pkr for b in breakdowns), Decimal(0))
    customs_subtotal = sum((b.customs_subtotal_pkr for b in breakdowns), Decimal(0))
    ait_total = sum((b.ait_pkr for b in breakdowns), Decimal(0))
    customs_total = sum((b.item_duty_total_pkr for b in breakdowns), Decimal(0))
    cf_pkr_total = sum((b.cf_value_pkr for b in breakdowns), Decimal(0))

    afu = iv_total * (to_decimal(afu_pct, DEFAULT_AFU_PCT) or Decimal(0)) + (
        to_decimal(afu_fixed_pkr, DEFAULT_AFU_FIXED_PKR) or Decimal(0)
    )
    stamp = to_decimal(stamp_fee_pkr, DEFAULT_STAMP_FEE_PKR) or Decimal(0)
    psw = to_decimal(psw_fee_pkr, DEFAULT_PSW_FEE_PKR) or Decimal(0)

    total_payable = customs_total + afu + stamp + psw

    return InvoiceSheetBreakdown(
        currency=currency,
        fx_rate=fx,
        items=breakdowns,
        invoice_value=sum(line_totals, Decimal(0)),
        freight=freight_total,
        cf_value_pkr=cf_pkr_total,
        import_value_pkr=iv_total,
        customs_subtotal_pkr=customs_subtotal,
        ait_pkr=ait_total,
        customs_total_pkr=customs_total,
        afu_pkr=afu,
        stamp_fee_pkr=stamp,
        psw_fee_pkr=psw,
        total_payable_pkr=total_payable,
        landed_cleared_price_pkr=cf_pkr_total + total_payable,
    )
