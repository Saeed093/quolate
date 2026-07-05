"""RAG expansion: tender documents/embeddings, chat message embeddings, global chat.

Revision ID: 0003_rag_expansion
Revises: 0002_library_documents
Create Date: 2026-07-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0003_rag_expansion"
down_revision: str = "0002_library_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1024

_uuid = postgresql.UUID(as_uuid=True)


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
    # 1. Tender detail URL (source page for background document downloads).
    op.add_column("tenders", sa.Column("detail_url", sa.String(), nullable=True))

    # 2. Downloaded tender attachments.
    op.create_table(
        "tender_documents",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("tender_id", _uuid, nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tender_id"], ["tenders.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "tender_id", "sha256", name="uq_tender_documents_tender_sha256"
        ),
    )

    # 3. Chunked full-text embeddings for tenders (detail page + attachments).
    op.create_table(
        "tender_embeddings",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("tender_id", _uuid, nullable=False),
        sa.Column("tender_document_id", _uuid, nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.ForeignKeyConstraint(["tender_id"], ["tenders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tender_document_id"], ["tender_documents.id"], ondelete="SET NULL"
        ),
    )

    # 4. Chat messages: owner scope (backfilled from project), global chats
    #    (nullable project), and per-message embedding.
    op.add_column("chat_messages", sa.Column("owner_id", _uuid, nullable=True))
    op.execute(
        "UPDATE chat_messages SET owner_id = projects.owner_id "
        "FROM projects WHERE chat_messages.project_id = projects.id"
    )
    # Any orphans (shouldn't exist) would block NOT NULL; delete defensively.
    op.execute("DELETE FROM chat_messages WHERE owner_id IS NULL")
    op.alter_column("chat_messages", "owner_id", nullable=False)
    op.create_foreign_key(
        "fk_chat_messages_owner_id_users",
        "chat_messages",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("chat_messages", "project_id", nullable=True)
    op.add_column(
        "chat_messages", sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "embedding")
    op.alter_column("chat_messages", "project_id", nullable=False)
    op.drop_constraint(
        "fk_chat_messages_owner_id_users", "chat_messages", type_="foreignkey"
    )
    op.drop_column("chat_messages", "owner_id")
    op.drop_table("tender_embeddings")
    op.drop_table("tender_documents")
    op.drop_column("tenders", "detail_url")
