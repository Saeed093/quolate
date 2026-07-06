"""baseline: all tables + pgvector

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1024

_uuid = postgresql.UUID(as_uuid=True)
_jsonb = postgresql.JSONB(astext_type=sa.Text())


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id", _uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "projects",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("owner_id", _uuid, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column(
            "base_currency", sa.String(), nullable=False, server_default="USD"
        ),
        sa.Column(
            "landed_cost_defaults", _jsonb, nullable=False, server_default="{}"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "bom_items",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("project_id", _uuid, nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("part_name", sa.String(), nullable=False),
        sa.Column("spec_requirement", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column("target_price", sa.Numeric(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
    )

    op.create_table(
        "suppliers",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("project_id", _uuid, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("contact", sa.String(), nullable=True),
        sa.Column("default_currency", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
    )

    op.create_table(
        "documents",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("project_id", _uuid, nullable=False),
        sa.Column("supplier_id", _uuid, nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("ocr_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("stage_log", _jsonb, nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"], ["suppliers.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "project_id", "sha256", name="uq_documents_project_sha256"
        ),
    )

    op.create_table(
        "extracted_fields",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("document_id", _uuid, nullable=False),
        sa.Column("bom_item_id", _uuid, nullable=True),
        sa.Column("supplier_id", _uuid, nullable=True),
        sa.Column("field_type", sa.String(), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_num", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("confidence", sa.Numeric(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="auto"),
        sa.Column("provenance", _jsonb, nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["bom_item_id"], ["bom_items.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"], ["suppliers.id"], ondelete="SET NULL"
        ),
    )

    op.create_table(
        "quotes",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("project_id", _uuid, nullable=False),
        sa.Column("supplier_id", _uuid, nullable=False),
        sa.Column("document_id", _uuid, nullable=True),
        sa.Column("bom_item_id", _uuid, nullable=True),
        sa.Column("unit_price", sa.Numeric(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("moq", sa.Numeric(), nullable=True),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("incoterms", sa.String(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("superseded_by", _uuid, nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"], ["suppliers.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["bom_item_id"], ["bom_items.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by"], ["quotes.id"], ondelete="SET NULL"
        ),
    )

    op.create_table(
        "chat_messages",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("project_id", _uuid, nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_calls", _jsonb, nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
    )

    op.create_table(
        "jobs",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("payload", _jsonb, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "document_embeddings",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("document_id", _uuid, nullable=False),
        sa.Column("project_id", _uuid, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
    )

    op.create_table(
        "tender_sources",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("owner_id", _uuid, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("adapter", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "tenders",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("source_id", _uuid, nullable=False),
        sa.Column("tender_no", sa.String(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("organization", sa.String(), nullable=True),
        sa.Column("org_type", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("sector_tags", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("closing_date", sa.Date(), nullable=True),
        sa.Column("advertise_date", sa.Date(), nullable=True),
        sa.Column("estimated_value", sa.Numeric(), nullable=True),
        sa.Column("notice_storage_key", sa.String(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("corrigendum_of", _uuid, nullable=True),
        sa.ForeignKeyConstraint(
            ["source_id"], ["tender_sources.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["corrigendum_of"], ["tenders.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint(
            "source_id", "tender_no", name="uq_tenders_source_tender_no"
        ),
    )

    op.create_table(
        "saved_filters",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("owner_id", _uuid, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("criteria", _jsonb, nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    for table in [
        "saved_filters",
        "tenders",
        "tender_sources",
        "document_embeddings",
        "jobs",
        "chat_messages",
        "quotes",
        "extracted_fields",
        "documents",
        "suppliers",
        "bom_items",
        "projects",
        "users",
    ]:
        op.drop_table(table)
