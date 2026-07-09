"""Per-BOM-line HS code for statutory duty in the comparison matrix.

Revision ID: 0009_bom_hs_code
Revises: 0008_audit_events
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_bom_hs_code"
down_revision: str = "0008_audit_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bom_items", sa.Column("hs_code", sa.String(length=20), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("bom_items", "hs_code")
