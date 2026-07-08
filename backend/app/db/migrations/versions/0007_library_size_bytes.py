"""Add size_bytes to library_documents for storage quota tracking.

Revision ID: 0007_library_size_bytes
Revises: 0006_hs_rate_memory
Create Date: 2026-07-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_library_size_bytes"
down_revision: str = "0006_hs_rate_memory"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "library_documents",
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.alter_column("library_documents", "size_bytes", server_default=None)


def downgrade() -> None:
    op.drop_column("library_documents", "size_bytes")
