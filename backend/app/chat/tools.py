"""Deterministic chat tools. Each tool is an async fn with a JSON-schema signature.

The model never computes numbers itself; every number it shows must come from a
tool result (enforced in loop.py). Tools are the only way to read/change state.
"""
from __future__ import annotations

import ast
import math
import operator
import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.web import get_web_client
from app.db.models import (
    Document,
    ExtractedField,
    Project,
    Supplier,
    Tender,
    TenderSource,
    User,
)
from app.duty.calculator import calculate_duty as _calculate_duty_fn
from app.duty.classifier import ClassificationInputError
from app.duty.classifier import classify_hs_code as _classify_hs_code_fn
from app.llm.client import get_llm_client
from app.llm.json_enforce import SchemaEnforceError
from app.matrix.builder import build_matrix
from app.tenders.correlation import (
    correlate_tender as _correlate_tender,
    correlate_tender_against_library,
)


@dataclass
class ChatContext:
    session: AsyncSession
    project: Project | None  # None => global assistant chat (no project tools)
    user: User
    currency: str | None = None
    overrides: dict = field(default_factory=dict)
    matrix_changed: bool = False
    last_matrix_hash: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: object  # async callable(ctx, **args) -> dict

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ---------- Tool implementations ----------
async def _tool_get_matrix(ctx: ChatContext, overrides: dict | None = None) -> dict:
    merged = {**ctx.overrides, **(overrides or {})}
    matrix = await build_matrix(
        ctx.session, ctx.project, currency=ctx.currency, overrides=merged
    )
    ctx.last_matrix_hash = matrix["matrix_hash"]
    return matrix


async def _tool_recompute_landed_cost(
    ctx: ChatContext,
    duty_pct: float | None = None,
    freight: float | None = None,
    lc_pct: float | None = None,
) -> dict:
    if duty_pct is not None:
        ctx.overrides["duty_pct"] = duty_pct
    if freight is not None:
        ctx.overrides["freight_per_unit"] = freight
    if lc_pct is not None:
        ctx.overrides["lc_pct"] = lc_pct
    ctx.matrix_changed = True
    matrix = await build_matrix(
        ctx.session, ctx.project, currency=ctx.currency, overrides=ctx.overrides
    )
    ctx.last_matrix_hash = matrix["matrix_hash"]
    return {
        "matrix_hash": matrix["matrix_hash"],
        "assumptions": matrix["assumptions"],
        "summary": matrix["summary"],
        "rows": matrix["rows"],
    }


async def _tool_list_documents(ctx: ChatContext) -> dict:
    rows = (
        await ctx.session.execute(
            select(Document)
            .where(Document.project_id == ctx.project.id)
            .order_by(Document.created_at.desc())
        )
    ).scalars().all()
    return {
        "documents": [
            {
                "id": str(d.id),
                "filename": d.original_filename,
                "kind": d.kind,
                "status": d.status,
            }
            for d in rows
        ]
    }


async def _tool_get_document_fields(ctx: ChatContext, document_id: str) -> dict:
    try:
        did = uuid.UUID(str(document_id))
    except (ValueError, TypeError):
        return {"error": "invalid document_id"}
    # Scope: document must belong to the project.
    doc = (
        await ctx.session.execute(
            select(Document).where(
                Document.id == did, Document.project_id == ctx.project.id
            )
        )
    ).scalar_one_or_none()
    if doc is None:
        return {"error": "document not found"}
    rows = (
        await ctx.session.execute(
            select(ExtractedField).where(ExtractedField.document_id == did)
        )
    ).scalars().all()
    return {
        "fields": [
            {
                "id": str(f.id),
                "field_type": f.field_type,
                "value_text": f.value_text,
                "value_num": float(f.value_num) if f.value_num is not None else None,
                "unit": f.unit,
                "confidence": float(f.confidence) if f.confidence is not None else None,
                "status": f.status,
            }
            for f in rows
        ]
    }


async def _tool_search_knowledge(ctx: ChatContext, query: str, top_k: int = 8) -> dict:
    """Semantic search across the user's tenders, quote docs and library docs."""
    import asyncio

    from app.chat.rag import search_all
    from app.config import settings
    from app.llm.embeddings import embed_text

    try:
        emb = await asyncio.wait_for(
            asyncio.to_thread(embed_text, query),
            timeout=settings.llm_fast_timeout_seconds,
        )
    except asyncio.TimeoutError:
        return {"error": "embedding service timed out"}
    try:
        k = max(1, min(int(top_k), 20))
    except (TypeError, ValueError):
        k = 8
    hits = await search_all(ctx.session, ctx.user.id, emb, top_k=k)
    return {"results": hits, "count": len(hits)}


async def _tool_web_search(ctx: ChatContext, query: str) -> dict:
    import asyncio

    results = await asyncio.to_thread(get_web_client().search, query, 5)
    return {"results": results}


async def _tool_fetch_url(ctx: ChatContext, url: str) -> dict:
    import asyncio

    text = await asyncio.to_thread(get_web_client().fetch, url)
    return {"url": url, "text": text}


async def _tool_search_tenders(
    ctx: ChatContext,
    keyword: str | None = None,
    category: str | None = None,
    org_type: str | None = None,
    city: str | None = None,
    status: str | None = None,
) -> dict:
    stmt = (
        select(Tender)
        .join(TenderSource, Tender.source_id == TenderSource.id)
        .where(TenderSource.owner_id == ctx.user.id)
    )
    if keyword:
        like = f"%{keyword.lower()}%"
        from sqlalchemy import func, or_

        stmt = stmt.where(
            or_(
                func.lower(Tender.title).like(like),
                func.lower(Tender.organization).like(like),
            )
        )
    if category:
        stmt = stmt.where(Tender.category == category)
    if org_type:
        stmt = stmt.where(Tender.org_type == org_type)
    if city:
        stmt = stmt.where(Tender.city == city)
    if status == "open":
        stmt = stmt.where(Tender.closing_date >= date.today())
    elif status == "closed":
        stmt = stmt.where(Tender.closing_date < date.today())
    stmt = stmt.order_by(Tender.closing_date).limit(25)

    rows = (await ctx.session.execute(stmt)).scalars().all()
    return {
        "tenders": [
            {
                "id": str(t.id),
                "tender_no": t.tender_no,
                "title": t.title,
                "organization": t.organization,
                "category": t.category,
                "city": t.city,
                "closing_date": t.closing_date.isoformat() if t.closing_date else None,
            }
            for t in rows
        ]
    }


async def _tool_correlate_tender(ctx: ChatContext, tender_id: str) -> dict:
    try:
        tid = uuid.UUID(str(tender_id))
    except (ValueError, TypeError):
        return {"error": "invalid tender_id"}
    tender = (
        await ctx.session.execute(
            select(Tender)
            .join(TenderSource, Tender.source_id == TenderSource.id)
            .where(Tender.id == tid, TenderSource.owner_id == ctx.user.id)
        )
    ).scalar_one_or_none()
    if tender is None:
        return {"error": "tender not found"}
    matches = await _correlate_tender(ctx.session, tender)
    library_matches = await correlate_tender_against_library(ctx.session, tender)
    return {
        "matches": matches,
        "library_matches": library_matches,
        "count": len(matches) + len(library_matches),
    }


async def _tool_draft_supplier_email(
    ctx: ChatContext, supplier_id: str, purpose: str
) -> dict:
    try:
        sid = uuid.UUID(str(supplier_id))
    except (ValueError, TypeError):
        return {"error": "invalid supplier_id"}
    supplier = (
        await ctx.session.execute(
            select(Supplier).where(
                Supplier.id == sid, Supplier.project_id == ctx.project.id
            )
        )
    ).scalar_one_or_none()
    if supplier is None:
        return {"error": "supplier not found"}

    import asyncio

    client = get_llm_client()
    messages = [
        {
            "role": "system",
            "content": (
                "You draft concise, professional procurement emails to suppliers. "
                "Do not invent prices or figures; leave placeholders if unknown."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Draft an email to supplier '{supplier.name}' "
                f"(country: {supplier.country or 'unknown'}). Purpose: {purpose}."
            ),
        },
    ]
    body = await asyncio.to_thread(client.chat, messages)
    return {"supplier": supplier.name, "draft": body}


async def _tool_calculate_duty(
    ctx: ChatContext,
    hs_code: str,
    declared_value_usd: float,
    exchange_rate: float,
    importer_category: str | None = None,
    atl_status: str | None = None,
    as_of_date: str | None = None,
) -> dict:
    """Compute the Pakistan import duty/tax stack for one HS code."""
    parsed_date: date | None = None
    if as_of_date:
        try:
            parsed_date = date.fromisoformat(as_of_date)
        except ValueError:
            return {"error": f"invalid as_of_date '{as_of_date}', expected YYYY-MM-DD"}
    try:
        breakdown = await _calculate_duty_fn(
            ctx.session,
            hs_code=hs_code,
            declared_value_usd=declared_value_usd,
            exchange_rate=exchange_rate,
            importer_category=importer_category,
            atl_status=atl_status,
            as_of_date=parsed_date,
        )
    except Exception as exc:  # bad decimal input, etc.
        return {"error": str(exc)}
    return {
        "hs_code": breakdown.hs_code,
        "declared_value_usd": breakdown.declared_value_usd,
        "exchange_rate": breakdown.exchange_rate,
        "assessed_value_pkr": breakdown.assessed_value_pkr,
        "importer_category": breakdown.importer_category,
        "atl_status": breakdown.atl_status,
        "as_of_date": breakdown.as_of_date,
        "levies": [
            {
                "levy_type": line.levy_type,
                "label": line.label,
                "rate": line.rate,
                "rate_type": line.rate_type,
                "basis_pkr": line.basis_pkr,
                "amount_pkr": line.amount_pkr,
                "legal_reference": line.legal_reference,
                "sro_reference": line.sro_reference,
                "exemption_applied": line.exemption_applied,
                "notes": line.notes,
            }
            for line in breakdown.lines
        ],
        "total_duty_tax_pkr": breakdown.total_duty_tax_pkr,
        "total_landed_pkr": breakdown.total_landed_pkr,
        "disclaimer": (
            "Calculation aid based on ingested rate data -- verify before "
            "relying on this for a client-facing quote or a filing."
        ),
    }


async def _tool_classify_hs_code(ctx: ChatContext, product_description: str) -> dict:
    """Suggest candidate Pakistan HS/PCT codes for a product description."""
    try:
        result = await _classify_hs_code_fn(ctx.session, text=product_description)
    except ClassificationInputError as exc:
        return {"error": str(exc)}
    except SchemaEnforceError as exc:
        return {"error": str(exc)}
    return {
        "product_summary": result.product_summary,
        "candidates": [c.model_dump() for c in result.candidates],
        "disclaimer": result.disclaimer,
    }


async def _tool_generate_quotation(
    ctx: ChatContext, title: str | None = None
) -> dict:
    """Create a sell-side quotation draft from the project's current BOM."""
    from app.db.models import QuotationVersion
    from app.quotations.assemble import create_quotation

    quotation = await create_quotation(ctx.session, ctx.project, title=title)
    await ctx.session.commit()
    version = (
        await ctx.session.execute(
            select(QuotationVersion).where(
                QuotationVersion.quotation_id == quotation.id
            )
        )
    ).scalar_one()
    gaps = [line.line_no for line in version.lines if line.gap_flag]
    return {
        "quote_no": quotation.quote_no,
        "quotation_id": str(quotation.id),
        "version_id": str(version.id),
        "currency": version.currency,
        "line_count": len(version.lines),
        "gap_line_nos": gaps,
        "subtotal": float(version.subtotal) if version.subtotal is not None else None,
        "tax_total": float(version.tax_total) if version.tax_total is not None else None,
        "grand_total": (
            float(version.grand_total) if version.grand_total is not None else None
        ),
        "lines": [
            {
                "line_no": line.line_no,
                "description": line.description,
                "quantity": float(line.qty) if line.qty is not None else None,
                "unit_price": (
                    float(line.unit_price) if line.unit_price is not None else None
                ),
                "line_total": (
                    float(line.line_total) if line.line_total is not None else None
                ),
                "gap": bool(line.gap_flag),
            }
            for line in version.lines
        ],
        "note": (
            "Draft created in the Quote tab. Lines flagged as gaps have no supplier "
            "cost — the user must set a price or remove them before sending."
            if gaps
            else "Draft created in the Quote tab; review and download it there."
        ),
    }


_CALC_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_CALC_FUNCS = {
    "sum": lambda args: sum(args),
    "avg": lambda args: sum(args) / len(args),
    "min": lambda args: min(args),
    "max": lambda args: max(args),
    "abs": lambda args: abs(args[0]),
    "round": lambda args: round(args[0], int(args[1])) if len(args) == 2 else round(args[0]),
}


def _calc_eval(node: ast.AST) -> float:
    """Evaluate a parsed arithmetic expression. Numbers and whitelisted ops only."""
    if isinstance(node, ast.Expression):
        return _calc_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise ValueError("only numbers are allowed")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _calc_eval(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_BINOPS:
        left, right = _calc_eval(node.left), _calc_eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 12:
            raise ValueError("exponent too large")
        return _CALC_BINOPS[type(node.op)](left, right)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _CALC_FUNCS
        and not node.keywords
    ):
        args: list[float] = []
        for arg in node.args:
            if isinstance(arg, (ast.List, ast.Tuple)):
                args.extend(_calc_eval(element) for element in arg.elts)
            else:
                args.append(_calc_eval(arg))
        if not args:
            raise ValueError(f"{node.func.id}() needs at least one number")
        return float(_CALC_FUNCS[node.func.id](args))
    raise ValueError("unsupported expression; use numbers, + - * / % **, sum/avg/min/max/abs/round")


async def _tool_calculate(ctx: ChatContext, expression: str = "") -> dict:
    expr = (expression or "").strip()
    if not expr:
        return {"error": "expression is required, e.g. '5 * 100.0'"}
    if len(expr) > 300:
        return {"error": "expression too long (max 300 chars)"}
    try:
        value = _calc_eval(ast.parse(expr, mode="eval"))
    except ZeroDivisionError:
        return {"error": "division by zero"}
    except (ValueError, SyntaxError) as exc:
        return {"error": f"invalid expression: {exc}"}
    if not math.isfinite(value):
        return {"error": "result is not a finite number"}
    return {"expression": expr, "result": round(value, 6)}


# ---------- Registry ----------
# Tools that only make sense inside a project workbench (need ctx.project).
_PROJECT_TOOLS = {
    "get_matrix",
    "recompute_landed_cost",
    "list_documents",
    "get_document_fields",
    "draft_supplier_email",
    "generate_quotation",
}


def build_registry(include_project_tools: bool = True) -> dict[str, Tool]:
    registry = {
        t.name: t
        for t in [
            Tool(
                "get_matrix",
                "Return the full computed comparison matrix (BOM lines x suppliers).",
                {
                    "type": "object",
                    "properties": {
                        "overrides": {
                            "type": "object",
                            "description": "Optional landed-cost overrides.",
                        }
                    },
                },
                _tool_get_matrix,
            ),
            Tool(
                "recompute_landed_cost",
                "Recompute the matrix with new duty_pct, freight (per unit) and/or "
                "lc_pct (all fractions, e.g. 0.1 for 10%).",
                {
                    "type": "object",
                    "properties": {
                        "duty_pct": {"type": "number"},
                        "freight": {"type": "number"},
                        "lc_pct": {"type": "number"},
                    },
                },
                _tool_recompute_landed_cost,
            ),
            Tool(
                "list_documents",
                "List uploaded supplier documents and their parse status.",
                {"type": "object", "properties": {}},
                _tool_list_documents,
            ),
            Tool(
                "get_document_fields",
                "Get the extracted fields for one document.",
                {
                    "type": "object",
                    "properties": {"document_id": {"type": "string"}},
                    "required": ["document_id"],
                },
                _tool_get_document_fields,
            ),
            Tool(
                "search_knowledge",
                "Semantic search across ALL the user's stored data: tenders and "
                "tender documents, supplier quote documents, the My Documents "
                "library, the user's own comments on documents, and past chat "
                "conversations. Use this to find past work, quotes or tenders "
                "related to any topic.",
                {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer"},
                    },
                    "required": ["query"],
                },
                _tool_search_knowledge,
            ),
            Tool(
                "calculate",
                "Evaluate an arithmetic expression and return the exact result. "
                "Use this for ANY math on figures from other tools (totals, "
                "averages, differences, percentages, conversions) instead of "
                "computing in your head. Supports + - * / % **, parentheses and "
                "sum(), avg(), min(), max(), abs(), round(). Numbers only, no "
                "variables. Example: sum(100.0, 250.5) * 1.18",
                {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "e.g. '5 * 100.0' or 'avg(10, 20, 30)'",
                        }
                    },
                    "required": ["expression"],
                },
                _tool_calculate,
            ),
            Tool(
                "web_search",
                "Search the web (DuckDuckGo). Returns titles, snippets and URLs.",
                {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                _tool_web_search,
            ),
            Tool(
                "fetch_url",
                "Fetch and extract readable text from a URL (capped at 8k chars).",
                {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
                _tool_fetch_url,
            ),
            Tool(
                "search_tenders",
                "Search stored tenders by keyword/category/org_type/city/status.",
                {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string"},
                        "category": {"type": "string"},
                        "org_type": {"type": "string"},
                        "city": {"type": "string"},
                        "status": {"type": "string", "enum": ["open", "closed"]},
                    },
                },
                _tool_search_tenders,
            ),
            Tool(
                "correlate_tender",
                "Find the user's existing quotes most similar to a tender.",
                {
                    "type": "object",
                    "properties": {"tender_id": {"type": "string"}},
                    "required": ["tender_id"],
                },
                _tool_correlate_tender,
            ),
            Tool(
                "draft_supplier_email",
                "Draft a professional email to a supplier for a given purpose.",
                {
                    "type": "object",
                    "properties": {
                        "supplier_id": {"type": "string"},
                        "purpose": {"type": "string"},
                    },
                    "required": ["supplier_id", "purpose"],
                },
                _tool_draft_supplier_email,
            ),
            Tool(
                "calculate_duty",
                "Compute the Pakistan import duty/tax stack (CD, ACD, RD, FED, "
                "ST, WHT/Section 148) for one HS/PCT code, given a declared "
                "value in USD and a PKR exchange rate. Returns the full "
                "levy-by-levy breakdown and totals.",
                {
                    "type": "object",
                    "properties": {
                        "hs_code": {
                            "type": "string",
                            "description": "Pakistan Customs Tariff code, e.g. '8517.12.00'.",
                        },
                        "declared_value_usd": {"type": "number"},
                        "exchange_rate": {
                            "type": "number",
                            "description": "Customs-notified PKR-per-USD rate.",
                        },
                        "importer_category": {
                            "type": "string",
                            "description": (
                                "e.g. industrial_undertaking_own_use, "
                                "commercial_importer. Omit for the general rate."
                            ),
                        },
                        "atl_status": {
                            "type": "string",
                            "enum": ["atl", "non_atl"],
                            "description": "Active Taxpayer List status -- affects Section 148.",
                        },
                        "as_of_date": {
                            "type": "string",
                            "description": "YYYY-MM-DD. Defaults to today.",
                        },
                    },
                    "required": ["hs_code", "declared_value_usd", "exchange_rate"],
                },
                _tool_calculate_duty,
            ),
            Tool(
                "classify_hs_code",
                "Suggest candidate Pakistan HS/PCT codes for a product from a "
                "free-text description. Returns 1-3 ranked candidates with "
                "confidence and reasoning -- a heuristic aid, not an "
                "authoritative ruling; the user should verify before relying "
                "on it, e.g. before calling calculate_duty.",
                {
                    "type": "object",
                    "properties": {
                        "product_description": {"type": "string"},
                    },
                    "required": ["product_description"],
                },
                _tool_classify_hs_code,
            ),
            Tool(
                "generate_quotation",
                "Create a sell-side quotation DRAFT for this project from its "
                "current BOM: prices each line from the cheapest supplier landed "
                "cost plus the project margin, applies GST if configured, and "
                "flags lines with no cost as gaps. Returns the quote number and "
                "totals; the user reviews, edits and downloads it (client DOCX + "
                "internal XLSX) in the Quote tab.",
                {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Optional quotation title/subject.",
                        },
                    },
                },
                _tool_generate_quotation,
            ),
        ]
    }
    if not include_project_tools:
        registry = {k: v for k, v in registry.items() if k not in _PROJECT_TOOLS}
    return registry
