"""Sell-side quotation router (owner-scoped).

Flow: extract requirements from RFP sources -> edit them (via the BOM router) ->
assemble a priced quotation version -> review/edit -> render DOCX + XLSX.
"""
from __future__ import annotations

import asyncio
import io
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import get_owned_project
from app.auth.deps import get_current_user
from app.db.models import Quotation, QuotationLine, QuotationVersion, User
from app.db.session import get_session
from app.llm.json_enforce import SchemaEnforceError
from app.quotations.assemble import (
    compute_totals,
    create_quotation,
    recompute_line,
)
from app.quotations.extract import RequirementSourceError, extract_requirements
from app.quotations.render_docx import render_quotation_docx
from app.quotations.render_xlsx import render_quotation_xlsx
from app.schemas import (
    BomItemOut,
    QuotationCreate,
    QuotationLineInput,
    QuotationOut,
    QuotationVersionOut,
    QuotationVersionUpdate,
)
from app.storage import storage

router = APIRouter(prefix="/projects/{project_id}/quotations", tags=["quotations"])

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _str(value: object) -> str | None:
    return str(value) if value is not None else None


def _render_data(quotation: Quotation, version: QuotationVersion) -> dict:
    return {
        "quote_no": quotation.quote_no,
        "title": quotation.title,
        "issue_date": version.created_at.date().isoformat() if version.created_at else None,
        "currency": version.currency,
        "validity_days": version.validity_days,
        "margin_pct": _str(version.margin_pct),
        "gst_enabled": bool(version.gst_enabled),
        "gst_pct": _str(version.gst_pct),
        "subtotal": _str(version.subtotal),
        "tax_total": _str(version.tax_total),
        "grand_total": _str(version.grand_total),
        "terms": version.terms_snapshot or {},
        "lines": [
            {
                "line_no": line.line_no,
                "description": line.description,
                "spec": line.spec,
                "qty": _str(line.qty),
                "unit_cost": _str(line.unit_cost),
                "unit_price": _str(line.unit_price),
                "line_total": _str(line.line_total),
                "cost_source": line.cost_source,
                "gap_flag": bool(line.gap_flag),
            }
            for line in version.lines
        ],
    }


async def _render_and_store(
    project_id: uuid.UUID, quotation: Quotation, version: QuotationVersion
) -> None:
    """Render both files and persist them; sets version.docx_key/xlsx_key."""
    data = _render_data(quotation, version)
    docx_bytes = await asyncio.to_thread(render_quotation_docx, data)
    xlsx_bytes = await asyncio.to_thread(render_quotation_xlsx, data)
    base = f"projects/{project_id}/quotations/{version.id}"
    docx_key, xlsx_key = f"{base}.docx", f"{base}.xlsx"
    await asyncio.to_thread(storage.save, docx_key, docx_bytes, _DOCX_MIME)
    await asyncio.to_thread(storage.save, xlsx_key, xlsx_bytes, _XLSX_MIME)
    version.docx_key = docx_key
    version.xlsx_key = xlsx_key


async def _get_quotation(
    session: AsyncSession, project_id: uuid.UUID, quotation_id: uuid.UUID
) -> Quotation:
    quotation = (
        await session.execute(
            select(Quotation).where(
                Quotation.id == quotation_id, Quotation.project_id == project_id
            )
        )
    ).scalar_one_or_none()
    if quotation is None:
        raise HTTPException(status_code=404, detail="quotation not found")
    return quotation


def _dec(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (ValueError, ArithmeticError):
        return None


async def _load_version(
    session: AsyncSession, project_id: uuid.UUID, version_id: uuid.UUID
) -> QuotationVersion:
    version = (
        await session.execute(
            select(QuotationVersion)
            .join(Quotation, QuotationVersion.quotation_id == Quotation.id)
            .where(
                QuotationVersion.id == version_id,
                Quotation.project_id == project_id,
            )
        )
    ).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="quotation version not found")
    return version


# ---------- Requirement extraction ----------
@router.post("/extract-requirements", response_model=list[BomItemOut], status_code=201)
async def extract_quotation_requirements(
    project_id: uuid.UUID,
    body: QuotationCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list:
    """Extract the customer's requested items from the given sources into the
    project BOM, ready to review/edit before generating a quotation."""
    project = await get_owned_project(project_id, user, session)
    try:
        items = await extract_requirements(session, project, body.sources)
    except RequirementSourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SchemaEnforceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    await session.commit()
    for item in items:
        await session.refresh(item)
    return items


# ---------- Quotation CRUD ----------
@router.post("", response_model=QuotationOut, status_code=201)
async def create_project_quotation(
    project_id: uuid.UUID,
    body: QuotationCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Quotation:
    """Assemble a priced draft quotation from the project's current BOM + matrix."""
    project = await get_owned_project(project_id, user, session)
    quotation = await create_quotation(session, project, title=body.title)
    await session.commit()
    # Re-fetch so the selectin relationships (versions -> lines) load eagerly
    # inside the async query for serialization.
    return (
        await session.execute(
            select(Quotation).where(Quotation.id == quotation.id)
        )
    ).scalar_one()


@router.get("", response_model=list[QuotationOut])
async def list_project_quotations(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Quotation]:
    await get_owned_project(project_id, user, session)
    rows = (
        await session.execute(
            select(Quotation)
            .where(Quotation.project_id == project_id)
            .order_by(Quotation.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


@router.get("/{quotation_id}", response_model=QuotationOut)
async def get_project_quotation(
    project_id: uuid.UUID,
    quotation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Quotation:
    await get_owned_project(project_id, user, session)
    quotation = (
        await session.execute(
            select(Quotation).where(
                Quotation.id == quotation_id, Quotation.project_id == project_id
            )
        )
    ).scalar_one_or_none()
    if quotation is None:
        raise HTTPException(status_code=404, detail="quotation not found")
    return quotation


# ---------- Version review/edit ----------
def _apply_line_edits(
    version: QuotationVersion, edits: list[QuotationLineInput]
) -> None:
    existing = {line.id: line for line in version.lines}
    max_line_no = max((line.line_no for line in version.lines), default=0)
    for edit in edits:
        if edit.id is not None:
            line = existing.get(edit.id)
            if line is None:
                continue
            if edit.remove:
                version.lines.remove(line)
                continue
            if edit.description is not None:
                line.description = edit.description
            if edit.spec is not None:
                line.spec = edit.spec
            if edit.qty is not None:
                line.qty = edit.qty
            if edit.unit_cost is not None:
                line.unit_cost = edit.unit_cost
            if edit.unit_price is not None:
                line.unit_price = edit.unit_price
                line.cost_source = "manual"
            elif edit.cost_source is not None:
                line.cost_source = edit.cost_source
        elif not edit.remove:
            # A brand-new manual line (e.g. filling a gap the matrix couldn't).
            max_line_no += 1
            version.lines.append(
                QuotationLine(
                    line_no=edit.line_no or max_line_no,
                    description=edit.description or "New item",
                    spec=edit.spec,
                    qty=edit.qty if edit.qty is not None else Decimal(1),
                    unit_cost=edit.unit_cost,
                    unit_price=edit.unit_price,
                    cost_source="manual" if edit.unit_price is not None else edit.cost_source,
                )
            )


@router.patch("/versions/{version_id}", response_model=QuotationVersionOut)
async def update_quotation_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    body: QuotationVersionUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> QuotationVersion:
    """Edit a draft version: adjust margin/GST/terms, edit lines, resolve gaps."""
    await get_owned_project(project_id, user, session)
    version = await _load_version(session, project_id, version_id)
    if version.status == "final":
        raise HTTPException(
            status_code=409, detail="a finalized version is immutable; regenerate instead"
        )

    if body.margin_pct is not None:
        version.margin_pct = body.margin_pct
    if body.gst_enabled is not None:
        version.gst_enabled = body.gst_enabled
    if body.gst_pct is not None:
        version.gst_pct = body.gst_pct
    if body.validity_days is not None:
        version.validity_days = body.validity_days
    if body.terms is not None:
        version.terms_snapshot = body.terms
    if body.lines is not None:
        _apply_line_edits(version, body.lines)

    margin = _dec(version.margin_pct) or Decimal(0)
    for line in version.lines:
        recompute_line(line, margin)
    subtotal, tax_total, grand_total = compute_totals(
        version.lines,
        gst_enabled=bool(version.gst_enabled),
        gst_pct=_dec(version.gst_pct) or Decimal(0),
    )
    version.subtotal = subtotal
    version.tax_total = tax_total
    version.grand_total = grand_total

    await session.commit()
    return version


# ---------- Render + download ----------
@router.post("/versions/{version_id}/render", response_model=QuotationVersionOut)
async def render_quotation_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> QuotationVersion:
    """(Re)build the client DOCX + internal XLSX and store them on the version."""
    await get_owned_project(project_id, user, session)
    version = await _load_version(session, project_id, version_id)
    quotation = await _get_quotation(session, project_id, version.quotation_id)
    await _render_and_store(project_id, quotation, version)
    await session.commit()
    return version


@router.get("/versions/{version_id}/download")
async def download_quotation_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    fmt: str = "docx",
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Stream a version's DOCX (client) or XLSX (internal). Renders on demand
    if the file has not been generated yet."""
    if fmt not in ("docx", "xlsx"):
        raise HTTPException(status_code=400, detail="fmt must be 'docx' or 'xlsx'")
    await get_owned_project(project_id, user, session)
    version = await _load_version(session, project_id, version_id)
    quotation = await _get_quotation(session, project_id, version.quotation_id)

    key = version.docx_key if fmt == "docx" else version.xlsx_key
    if not key or not storage.exists(key):
        await _render_and_store(project_id, quotation, version)
        await session.commit()
        key = version.docx_key if fmt == "docx" else version.xlsx_key

    data = await asyncio.to_thread(storage.get, key)
    filename = f"{quotation.quote_no}-v{version.version_no}.{fmt}"
    mime = _DOCX_MIME if fmt == "docx" else _XLSX_MIME
    return StreamingResponse(
        io.BytesIO(data),
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- Versioning ----------
@router.post("/versions/{version_id}/regenerate", response_model=QuotationVersionOut)
async def regenerate_quotation_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> QuotationVersion:
    """Clone a version (its edited lines + settings) into a new draft version.

    Every prior version and its files are retained (Claude-style history), so a
    finalized version stays intact while the user iterates on a fresh copy.
    """
    await get_owned_project(project_id, user, session)
    source = await _load_version(session, project_id, version_id)
    quotation = await _get_quotation(session, project_id, source.quotation_id)

    next_no = int(
        (
            await session.execute(
                select(func.max(QuotationVersion.version_no)).where(
                    QuotationVersion.quotation_id == quotation.id
                )
            )
        ).scalar_one()
        or 0
    ) + 1

    new_version = QuotationVersion(
        quotation_id=quotation.id,
        version_no=next_no,
        status="draft",
        currency=source.currency,
        margin_pct=source.margin_pct,
        gst_enabled=source.gst_enabled,
        gst_pct=source.gst_pct,
        validity_days=source.validity_days,
        terms_snapshot=dict(source.terms_snapshot or {}),
        subtotal=source.subtotal,
        tax_total=source.tax_total,
        grand_total=source.grand_total,
    )
    new_version.lines = [
        QuotationLine(
            line_no=line.line_no,
            description=line.description,
            spec=line.spec,
            qty=line.qty,
            unit_cost=line.unit_cost,
            cost_source=line.cost_source,
            unit_price=line.unit_price,
            line_total=line.line_total,
            gap_flag=line.gap_flag,
        )
        for line in source.lines
    ]
    session.add(new_version)
    quotation.status = "draft"
    await session.commit()
    return (
        await session.execute(
            select(QuotationVersion).where(QuotationVersion.id == new_version.id)
        )
    ).scalar_one()


@router.post("/versions/{version_id}/finalize", response_model=QuotationVersionOut)
async def finalize_quotation_version(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> QuotationVersion:
    """Lock a version as final (immutable) and render its canonical files."""
    await get_owned_project(project_id, user, session)
    version = await _load_version(session, project_id, version_id)
    quotation = await _get_quotation(session, project_id, version.quotation_id)
    version.status = "final"
    quotation.status = "final"
    await _render_and_store(project_id, quotation, version)
    await session.commit()
    return version
