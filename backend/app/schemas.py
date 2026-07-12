"""Pydantic v2 request/response schemas."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- Auth ----
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    display_name: str | None


# ---- Projects ----
class ProjectCreate(BaseModel):
    name: str
    base_currency: str = "USD"
    landed_cost_defaults: dict = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    base_currency: str | None = None
    landed_cost_defaults: dict | None = None
    # Sell-side quotation defaults (fractions; terms is a free-form dict).
    margin_pct: Decimal | None = None
    gst_enabled: bool | None = None
    gst_pct: Decimal | None = None
    terms: dict | None = None


class ProjectOut(ORMModel):
    id: uuid.UUID
    name: str
    status: str
    base_currency: str
    landed_cost_defaults: dict
    margin_pct: Decimal
    gst_enabled: bool
    gst_pct: Decimal
    terms: dict
    created_at: datetime


# ---- Suppliers ----
class SupplierCreate(BaseModel):
    name: str
    country: str | None = None
    contact: str | None = None
    default_currency: str | None = None


class SupplierUpdate(BaseModel):
    name: str | None = None
    country: str | None = None
    contact: str | None = None
    default_currency: str | None = None


class SupplierOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    country: str | None
    contact: str | None
    default_currency: str | None


# ---- BOM ----
class BomItemCreate(BaseModel):
    line_no: int | None = None
    part_name: str
    spec_requirement: str | None = None
    quantity: Decimal | None = None
    target_price: Decimal | None = None
    notes: str | None = None
    hs_code: str | None = None


class BomItemUpdate(BaseModel):
    line_no: int | None = None
    part_name: str | None = None
    spec_requirement: str | None = None
    quantity: Decimal | None = None
    target_price: Decimal | None = None
    notes: str | None = None
    hs_code: str | None = None


class BomItemOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    line_no: int
    part_name: str
    spec_requirement: str | None
    quantity: Decimal | None
    target_price: Decimal | None
    notes: str | None
    hs_code: str | None


class BomPasteRequest(BaseModel):
    """Raw clipboard TSV pasted from Excel."""

    text: str
    has_header: bool | None = None


# ---- Quotations (sell-side) ----
class QuotationSourceRef(BaseModel):
    """One RFP/requirement source to extract line items from."""

    # "document" (project doc), "library" (My Documents), "tender", or "text".
    kind: str
    id: uuid.UUID | None = None
    text: str | None = None


class QuotationCreate(BaseModel):
    title: str | None = None
    sources: list[QuotationSourceRef] = Field(default_factory=list)


class QuotationLineInput(BaseModel):
    """Edit/resolve a line at review. `remove=True` deletes it (gap resolution)."""

    id: uuid.UUID | None = None
    line_no: int | None = None
    description: str | None = None
    spec: str | None = None
    qty: Decimal | None = None
    unit_cost: Decimal | None = None
    unit_price: Decimal | None = None
    cost_source: str | None = None
    remove: bool = False


class QuotationVersionUpdate(BaseModel):
    margin_pct: Decimal | None = None
    gst_enabled: bool | None = None
    gst_pct: Decimal | None = None
    validity_days: int | None = None
    terms: dict | None = None
    lines: list[QuotationLineInput] | None = None


class QuotationLineOut(ORMModel):
    id: uuid.UUID
    version_id: uuid.UUID
    line_no: int
    description: str
    spec: str | None
    qty: Decimal | None
    unit_cost: Decimal | None
    cost_source: str | None
    unit_price: Decimal | None
    line_total: Decimal | None
    gap_flag: bool


class QuotationVersionOut(ORMModel):
    id: uuid.UUID
    quotation_id: uuid.UUID
    version_no: int
    status: str
    currency: str
    margin_pct: Decimal
    gst_enabled: bool
    gst_pct: Decimal
    validity_days: int | None
    terms_snapshot: dict
    subtotal: Decimal | None
    tax_total: Decimal | None
    grand_total: Decimal | None
    docx_key: str | None
    xlsx_key: str | None
    created_at: datetime
    lines: list[QuotationLineOut] = Field(default_factory=list)


class QuotationOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    quote_no: str
    seq: int
    title: str | None
    status: str
    created_at: datetime
    versions: list[QuotationVersionOut] = Field(default_factory=list)


# ---- Documents ----
class DocumentOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    supplier_id: uuid.UUID | None
    kind: str
    original_filename: str
    mime_type: str | None
    status: str
    page_count: int | None
    ocr_used: bool
    error: str | None
    created_at: datetime
    auto_bom_created: int = 0

    @model_validator(mode="wrap")
    @classmethod
    def _inject_auto_bom(cls, value, handler):
        out = handler(value)
        if hasattr(value, "stage_log"):
            persist = (value.stage_log or {}).get("persist") or {}
            if isinstance(persist, dict):
                out.auto_bom_created = int(persist.get("auto_bom_created") or 0)
        return out


class ExtractedFieldOut(ORMModel):
    id: uuid.UUID
    document_id: uuid.UUID
    bom_item_id: uuid.UUID | None
    supplier_id: uuid.UUID | None
    field_type: str
    value_text: str | None
    value_num: Decimal | None
    unit: str | None
    confidence: Decimal | None
    status: str
    provenance: dict


class FieldUpdate(BaseModel):
    value_text: str | None = None
    value_num: Decimal | None = None
    unit: str | None = None
    status: str | None = None  # confirmed|edited|rejected
    bom_item_id: uuid.UUID | None = None


class DocumentReview(BaseModel):
    document: DocumentOut
    fields: list[ExtractedFieldOut]
    page_urls: list[str]


# ---- Chat ----
class ChatRequest(BaseModel):
    message: str
    currency: str | None = None
    overrides: dict | None = None


class ChatMessageOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    role: str
    content: str
    tool_calls: dict | None
    created_at: datetime


# ---- Tenders ----
class TenderSourceCreate(BaseModel):
    name: str
    base_url: str
    adapter: str = "generic"


class TenderSourceUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    adapter: str | None = None
    enabled: bool | None = None


class TenderSourceOut(ORMModel):
    id: uuid.UUID
    name: str
    base_url: str
    adapter: str
    enabled: bool
    last_run: datetime | None
    last_status: str | None


class TenderOut(ORMModel):
    id: uuid.UUID
    source_id: uuid.UUID
    tender_no: str | None
    title: str | None
    organization: str | None
    org_type: str | None
    category: str | None
    sector_tags: list[str] | None
    city: str | None
    closing_date: date | None
    advertise_date: date | None
    estimated_value: Decimal | None
    corrigendum_of: uuid.UUID | None
    created_at: datetime


class SavedFilterCreate(BaseModel):
    name: str
    criteria: dict = Field(default_factory=dict)


class SavedFilterOut(ORMModel):
    id: uuid.UUID
    name: str
    criteria: dict


# ---- Activity ----
class TenderPullActivity(BaseModel):
    source_id: uuid.UUID
    source_name: str
    status: str


class ActivityOut(BaseModel):
    documents_processing: int
    tender_pulls: list[TenderPullActivity]
