"""Deterministic chat tools. Each tool is an async fn with a JSON-schema signature.

The model never computes numbers itself; every number it shows must come from a
tool result (enforced in loop.py). Tools are the only way to read/change state.
"""
from __future__ import annotations

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
from app.llm.client import get_llm_client
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


# ---------- Registry ----------
# Tools that only make sense inside a project workbench (need ctx.project).
_PROJECT_TOOLS = {
    "get_matrix",
    "recompute_landed_cost",
    "list_documents",
    "get_document_fields",
    "draft_supplier_email",
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
        ]
    }
    if not include_project_tools:
        registry = {k: v for k, v in registry.items() if k not in _PROJECT_TOOLS}
    return registry
