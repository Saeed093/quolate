"""LLM extraction of invoice/quotation line items for the duty calculator.

One LLM call per document (no chunking -- cross-chunk line-item continuity
isn't worth the complexity at this model size); HS classification of each
extracted item is a separate, frontend-driven step reusing the existing
`classify_hs_code` so its already-tuned prompt stays single-purpose.

Amounts come back from the model as VERBATIM strings and are parsed here,
deterministically: supplier documents mix decimal/thousands conventions
("$27.500" meaning 27.50 with a padded third decimal, "8,770.000" meaning
8770.00, European "1.234,56"), and an LLM asked to normalise them silently
drops separators. Ambiguous forms (a single separator followed by exactly
three digits) yield both readings, and the one satisfying
quantity x unit_price = line_total wins.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.duty.classifier import ClassificationInputError, load_document_text
from app.duty.schemas import InvoiceItemParsed, InvoiceParseOut
from app.llm.client import get_llm_client
from app.llm.json_enforce import SchemaEnforceError, complete_json
from app.llm.prompts import INVOICE_ITEMS_SCHEMA, build_invoice_items_messages
from app.matrix.landed_cost import to_decimal

#: Larger than the classifier's 6000 -- invoice tables run wide -- but still
#: comfortably inside LLM_NUM_CTX=8192 tokens (~4 chars/token).
INVOICE_TEXT_BUDGET = 12000

#: Hard cap on extracted items (also stated in the prompt).
MAX_ITEMS = 20

#: Everything that isn't a digit or a separator: currency symbols, codes,
#: units, whitespace (incl. non-breaking) -- stripped before parsing.
_NON_AMOUNT_RE = re.compile(r"[^\d.,\-]")


def _dec(text: str) -> Decimal | None:
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def amount_candidates(raw: object) -> list[Decimal]:
    """Possible readings of one verbatim amount, most likely first.

    Unambiguous forms give one candidate. A single separator followed by
    exactly three digits gives two ("27.500" -> 27.5 or 27500; "1,500" ->
    1500 or 1.5) ordered by the separator's usual role -- dot reads as a
    decimal point first, comma as a thousands separator first -- and the
    caller disambiguates against qty x price = total.
    """
    if raw is None:
        return []
    if isinstance(raw, (int, float, Decimal)):
        value = to_decimal(raw)
        return [value] if value is not None else []

    text = _NON_AMOUNT_RE.sub("", str(raw).strip())
    negative = text.startswith("-")
    text = text.replace("-", "")
    if not text.strip(".,"):
        return []

    has_dot, has_comma = "." in text, "," in text
    if has_dot and has_comma:
        # The rightmost separator is the decimal point; the other groups.
        if text.rfind(".") > text.rfind(","):
            candidates = [_dec(text.replace(",", ""))]
        else:
            candidates = [_dec(text.replace(".", "").replace(",", "."))]
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        head, *rest = text.split(sep)
        if len(rest) > 1:  # "8.770.000" -- repeated separator only groups
            candidates = [_dec(text.replace(sep, ""))]
        else:
            tail = rest[0]
            as_decimal = _dec(f"{head or '0'}.{tail or '0'}")
            if head and len(tail) == 3:
                as_grouping = _dec(head + tail)
                candidates = (
                    [as_decimal, as_grouping] if sep == "." else [as_grouping, as_decimal]
                )
            else:
                candidates = [as_decimal]
    else:
        candidates = [_dec(text)]

    unique: list[Decimal] = []
    for candidate in candidates:
        if candidate is None:
            continue
        if negative:
            candidate = -candidate
        if candidate not in unique:
            unique.append(candidate)
    return unique


def resolve_item_amounts(
    quantity_raw: object, unit_price_raw: object, line_total_raw: object
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Pick the (quantity, unit_price, line_total) reading that reconciles.

    The first candidate combination satisfying qty x price = total (within
    rounding tolerance) wins; with no consistent combination -- or a missing
    leg -- the most-likely readings stand, and a missing total is backfilled
    from qty x price.
    """
    qty_c = amount_candidates(quantity_raw)
    price_c = amount_candidates(unit_price_raw)
    total_c = amount_candidates(line_total_raw)

    for qty in qty_c:
        for price in price_c:
            expected = qty * price
            for total in total_c:
                tolerance = max(Decimal("0.02"), abs(total) * Decimal("0.005"))
                if abs(expected - total) <= tolerance:
                    return qty, price, total

    qty = qty_c[0] if qty_c else None
    price = price_c[0] if price_c else None
    total = total_c[0] if total_c else None
    if total is None and qty is not None and price is not None:
        total = qty * price
    return qty, price, total


async def parse_invoice_items(
    session: AsyncSession,
    *,
    text: str | None = None,
    library_document_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
) -> InvoiceParseOut:
    """Extract line items (+ currency/freight) from an invoice or quotation.

    Exactly one of `text` or `library_document_id` should be provided (the
    document wins if both are), mirroring `classify_hs_code`.
    """
    if library_document_id is not None:
        if owner_id is None:
            raise ClassificationInputError(
                "owner_id is required when parsing a library document."
            )
        resolved_text = await load_document_text(
            session, library_document_id, owner_id, text_budget=INVOICE_TEXT_BUDGET
        )
    elif text is not None and text.strip():
        resolved_text = text.strip()[:INVOICE_TEXT_BUDGET]
    else:
        raise ClassificationInputError("Provide either 'text' or 'library_document_id'.")

    client = get_llm_client()
    messages = build_invoice_items_messages(resolved_text)
    try:
        parsed = await asyncio.to_thread(
            complete_json,
            client,
            messages,
            INVOICE_ITEMS_SCHEMA,
            think=not settings.llm_disable_thinking_for_fast_calls,
            timeout=settings.llm_fast_timeout_seconds,
        )
    except SchemaEnforceError as exc:
        raise SchemaEnforceError(
            "Invoice line-item extraction failed -- the model could not "
            "produce a valid response. Try again, or paste the invoice text."
        ) from exc

    if isinstance(parsed, list):
        parsed = {"items": parsed}

    items: list[InvoiceItemParsed] = []
    for raw in (parsed.get("items") or [])[:MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        description = str(raw.get("description") or "").strip()
        if not description:
            continue
        quantity, unit_price, line_total = resolve_item_amounts(
            raw.get("quantity"), raw.get("unit_price"), raw.get("line_total")
        )
        line_no = raw.get("line_no")
        items.append(
            InvoiceItemParsed(
                line_no=int(line_no) if isinstance(line_no, (int, float)) else None,
                description=description,
                quantity=quantity,
                unit=(str(raw["unit"]).strip() or None) if raw.get("unit") else None,
                unit_price=unit_price,
                line_total=line_total,
            )
        )

    currency_raw = parsed.get("invoice_currency")
    currency = str(currency_raw).strip().upper() if currency_raw else None

    freight_candidates = amount_candidates(parsed.get("freight"))
    freight = freight_candidates[0] if freight_candidates else Decimal(0)

    return InvoiceParseOut(
        invoice_currency=currency,
        freight=max(freight, Decimal(0)),
        items=items,
    )
