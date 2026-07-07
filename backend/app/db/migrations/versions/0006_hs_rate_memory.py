"""Per-user remembered duty rates per HS code (invoice duty calculator).

Revision ID: 0006_hs_rate_memory
Revises: 0005_duty_engine
Create Date: 2026-07-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_hs_rate_memory"
down_revision: str = "0005_duty_engine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

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
    op.create_table(
        "hs_rate_memory",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("owner_id", _uuid, nullable=False),
        sa.Column("hs_code", sa.String(length=20), nullable=False),
        sa.Column(
            "rates",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("owner_id", "hs_code", name="uq_hs_rate_memory_owner_hs"),
    )
    op.create_index("ix_hs_rate_memory_owner", "hs_rate_memory", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_hs_rate_memory_owner", table_name="hs_rate_memory")
    op.drop_table("hs_rate_memory")
