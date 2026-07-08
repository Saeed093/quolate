"""Compliance audit trail: audit_events table.

Revision ID: 0008_audit_events
Revises: 0007_library_size_bytes
Create Date: 2026-07-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_audit_events"
down_revision: str = "0007_library_size_bytes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_uuid = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column(
            "id", _uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "user_id",
            _uuid,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("query", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
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
    )
    op.create_index(
        "ix_audit_events_user_created", "audit_events", ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_user_created", table_name="audit_events")
    op.drop_table("audit_events")
