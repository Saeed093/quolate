"""All ORM models (spec section 3).

Every user-data table carries owner_id (directly or via a parent row) so all
queries can be scoped per user (multi-user per instance).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.db.base import Base, TimestampMixin, UUIDPKMixin


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)


class Project(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="active", nullable=False)
    base_currency: Mapped[str] = mapped_column(String, default="USD", nullable=False)
    # {duty_pct, freight_per_unit, lc_pct, fx_overrides:{...}}
    landed_cost_defaults: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False
    )


class BomItem(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "bom_items"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    part_name: Mapped[str] = mapped_column(String, nullable=False)
    spec_requirement: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    target_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Pakistan PCT/HS code for statutory duty in the comparison matrix.
    hs_code: Mapped[str | None] = mapped_column(String(20), nullable=True)


class Supplier(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    contact: Mapped[str | None] = mapped_column(String, nullable=True)
    default_currency: Mapped[str | None] = mapped_column(String, nullable=True)


class Document(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("project_id", "sha256", name="uq_documents_project_sha256"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)  # quote|datasheet|...
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Free-form stage log for debugging the pipeline.
    stage_log: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ExtractedField(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "extracted_fields"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    bom_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bom_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True,
    )
    field_type: Mapped[str] = mapped_column(String, nullable=False)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_num: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric, nullable=True)  # 0..1
    status: Mapped[str] = mapped_column(String, default="auto", nullable=False)
    # {page, bbox:[x0,y0,x1,y1]|null, source_snippet}
    provenance: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Quote(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "quotes"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("suppliers.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    bom_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("bom_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    unit_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    currency: Mapped[str | None] = mapped_column(String, nullable=True)
    moq: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    incoterms: Mapped[str | None] = mapped_column(String, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quotes.id", ondelete="SET NULL"),
        nullable=True,
    )


class ChatMessage(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "chat_messages"

    # Nullable: global (project-independent) assistant chats have no project.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Semantic-search vector over content (populated by the embed_chat_message job).
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )


class Job(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "jobs"

    type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String, default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DocumentEmbedding(UUIDPKMixin, TimestampMixin, Base):
    """Quote-text embeddings per document for tender correlation."""

    __tablename__ = "document_embeddings"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )


class TenderSource(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "tender_sources"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str] = mapped_column(String, nullable=False)
    adapter: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_status: Mapped[str | None] = mapped_column(String, nullable=True)


class Tender(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "tenders"
    __table_args__ = (
        UniqueConstraint("source_id", "tender_no", name="uq_tenders_source_tender_no"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tender_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    tender_no: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    organization: Mapped[str | None] = mapped_column(String, nullable=True)
    org_type: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    sector_tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    closing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    advertise_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    estimated_value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    notice_storage_key: Mapped[str | None] = mapped_column(String, nullable=True)
    detail_url: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )
    corrigendum_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenders.id", ondelete="SET NULL"),
        nullable=True,
    )


class TenderDocument(UUIDPKMixin, TimestampMixin, Base):
    """A downloaded tender attachment (tender document / advertisement PDF)."""

    __tablename__ = "tender_documents"
    __table_args__ = (
        UniqueConstraint("tender_id", "sha256", name="uq_tender_documents_tender_sha256"),
    )

    tender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class TenderEmbedding(UUIDPKMixin, TimestampMixin, Base):
    """Chunked full-text embeddings for a tender.

    tender_document_id is NULL for detail-page text chunks, set for chunks
    extracted from a downloaded tender document.
    """

    __tablename__ = "tender_embeddings"

    tender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False
    )
    tender_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tender_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )


class SavedFilter(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "saved_filters"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    criteria: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class LibraryDocument(UUIDPKMixin, TimestampMixin, Base):
    """Global document library (not project-scoped) for past work references."""

    __tablename__ = "library_documents"
    __table_args__ = (
        UniqueConstraint("owner_id", "sha256", name="uq_library_documents_owner_sha256"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage_log: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")


class LibraryDocumentEmbedding(UUIDPKMixin, TimestampMixin, Base):
    """Embeddings for library documents for semantic correlation."""

    __tablename__ = "library_document_embeddings"

    library_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("library_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )


class LibraryDocumentComment(UUIDPKMixin, TimestampMixin, Base):
    """User comments on a library document (embedded for assistant recall)."""

    __tablename__ = "library_document_comments"

    library_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("library_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )


class DutyTaxRate(UUIDPKMixin, TimestampMixin, Base):
    """A single dated rate for one levy on one HS code (Pakistan duty engine).

    `hs_code` uses the literal wildcard ``"*"`` for schedules that are not
    keyed by HS code at all -- e.g. the standard Sales Tax rate, or an ACD/RD
    slab schedule keyed on the *CD rate bracket* rather than the HS code
    (see `slab_rules`). `importer_category`/`atl_status` are nullable: a NULL
    value is the general/default rate, and a specific value only matches an
    importer who declares that exact category/status (spec section 1, 3).

    Rows are never overwritten -- a rate change inserts a new row and sets
    `effective_to` (and `superseded_by`) on the old one, so a calculation run
    with an old `as_of_date` stays reproducible for audit/quoting purposes.
    """

    __tablename__ = "duty_tax_rates"
    __table_args__ = (
        CheckConstraint(
            "levy_type IN ('CD','ACD','RD','ST','FED','WHT_148')",
            name="ck_duty_tax_rates_levy_type",
        ),
        CheckConstraint(
            "rate_type IN ('percent','fixed','slab')",
            name="ck_duty_tax_rates_rate_type",
        ),
        CheckConstraint(
            "atl_status IS NULL OR atl_status IN ('atl','non_atl')",
            name="ck_duty_tax_rates_atl_status",
        ),
        CheckConstraint(
            "status IN ('pending_review','approved','rejected')",
            name="ck_duty_tax_rates_status",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_duty_tax_rates_effective_range",
        ),
        Index(
            "ix_duty_tax_rates_hs_levy_effective",
            "hs_code",
            "levy_type",
            "effective_from",
        ),
        Index(
            "ix_duty_tax_rates_current",
            "hs_code",
            "levy_type",
            postgresql_where=text("effective_to IS NULL AND status = 'approved'"),
        ),
    )

    hs_code: Mapped[str] = mapped_column(String(10), nullable=False)
    levy_type: Mapped[str] = mapped_column(String(10), nullable=False)
    rate_type: Mapped[str] = mapped_column(String(10), nullable=False)
    # Fraction for percent rates (0.20 == 20%); PKR amount for fixed rates;
    # NULL when rate_type == 'slab' (see slab_rules).
    rate_value: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    # rate_type == 'slab': [{cd_rate_min, cd_rate_max, rate, sro_reference?,
    # legal_reference?, notes?}, ...] -- preserves the source SRO's bracket
    # logic (e.g. "if CD falls in bracket X, ACD = Y%") instead of collapsing
    # it into one flat percentage.
    slab_rules: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    importer_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    atl_status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    sro_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    legal_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("duty_tax_rates.id", ondelete="SET NULL"),
        nullable=True,
    )
    # pending_review|approved|rejected -- LLM-extracted rates land as
    # pending_review and must be approved before the resolver will use them.
    status: Mapped[str] = mapped_column(String(20), default="approved", nullable=False)
    source_document: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ExemptionRule(UUIDPKMixin, TimestampMixin, Base):
    """Conditional exemption/reduced-rate rule.

    Unlike `DutyTaxRate`, these are gated on importer category / certificate
    rather than being a pure HS-code rate lookup (e.g. "industrial
    undertaking, own use" exemptions from Section 148, or project-specific
    SRO exemptions requiring an FBR certificate). `hs_code` is nullable
    because some exemptions apply across an entire certificate scheme rather
    than a single HS code.
    """

    __tablename__ = "exemption_rules"
    __table_args__ = (
        CheckConstraint(
            "levy_type IN ('CD','ACD','RD','ST','FED','WHT_148')",
            name="ck_exemption_rules_levy_type",
        ),
        CheckConstraint(
            "exemption_type IN ('full','reduced_rate')",
            name="ck_exemption_rules_exemption_type",
        ),
        CheckConstraint(
            "exemption_type <> 'reduced_rate' OR reduced_rate IS NOT NULL",
            name="ck_exemption_rules_reduced_rate_required",
        ),
        CheckConstraint(
            "status IN ('pending_review','approved','rejected')",
            name="ck_exemption_rules_status",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_exemption_rules_effective_range",
        ),
        Index("ix_exemption_rules_hs_levy", "hs_code", "levy_type"),
        Index("ix_exemption_rules_importer_category", "importer_category"),
    )

    hs_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    levy_type: Mapped[str] = mapped_column(String(10), nullable=False)
    importer_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    certificate_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requires_certificate: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    exemption_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reduced_rate: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    condition_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sro_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    schedule_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="approved", nullable=False)
    source_document: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class HsRateMemory(UUIDPKMixin, TimestampMixin, Base):
    """Per-user remembered duty rates for one HS code (invoice calculator).

    Unlike `DutyTaxRate` (global, dated, review-gated, statutory levy types
    only), this is a lightweight owner-scoped prefill memory: whenever the
    user runs an invoice calculation, the rates they confirmed for each HS
    code are upserted here and offered as the prefill next time that code
    appears. `rates` holds fractions keyed cd/acd/rd/st/ast/ait plus
    fed_amount_pkr (a PKR amount, not a rate).
    """

    __tablename__ = "hs_rate_memory"
    __table_args__ = (
        UniqueConstraint("owner_id", "hs_code", name="uq_hs_rate_memory_owner_hs"),
        Index("ix_hs_rate_memory_owner", "owner_id"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Wider than duty_tax_rates.hs_code(10): the classifier can emit longer
    # dotted PCT codes and this column stores them verbatim.
    hs_code: Mapped[str] = mapped_column(String(20), nullable=False)
    rates: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class ProjectLibraryDocument(TimestampMixin, Base):
    """Link table: library documents attached to a project."""

    __tablename__ = "project_library_documents"
    __table_args__ = (
        UniqueConstraint("project_id", "library_document_id", name="uq_project_library_doc"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    library_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("library_documents.id", ondelete="CASCADE"),
        nullable=False,
    )


class AuditEvent(UUIDPKMixin, TimestampMixin, Base):
    """Compliance audit trail: one row per recorded user action.

    Populated by the audit middleware (app.audit) for mutating requests and
    duty calculations. Read by the admin console.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String, nullable=False)  # human label
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
