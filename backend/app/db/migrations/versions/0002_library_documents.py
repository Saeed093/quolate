"""Add library documents tables for global document library feature.

Revision ID: 0002_library_documents
Revises: 0001_baseline
Create Date: 2026-07-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002_library_documents"
down_revision: str = "0001_baseline"
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
    op.create_table(
        "library_documents",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("owner_id", _uuid, nullable=False),
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
            ["owner_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "owner_id", "sha256", name="uq_library_documents_owner_sha256"
        ),
    )

    op.create_table(
        "library_document_embeddings",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("library_document_id", _uuid, nullable=False),
        sa.Column("owner_id", _uuid, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.ForeignKeyConstraint(
            ["library_document_id"], ["library_documents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], ondelete="CASCADE"
        ),
    )

    op.create_table(
        "project_library_documents",
        sa.Column(
            "id", _uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("project_id", _uuid, nullable=False),
        sa.Column("library_document_id", _uuid, nullable=False),
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
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["library_document_id"], ["library_documents.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "project_id", "library_document_id", name="uq_project_library_doc"
        ),
    )


def downgrade() -> None:
    op.drop_table("project_library_documents")
    op.drop_table("library_document_embeddings")
    op.drop_table("library_documents")
