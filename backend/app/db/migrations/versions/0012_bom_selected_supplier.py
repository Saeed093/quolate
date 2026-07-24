"""Per-BOM-line chosen supplier for the quotation (Compare page selection).

Revision ID: 0012_bom_selected_supplier
Revises: 0011_document_ocr_langs
Create Date: 2026-07-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_bom_selected_supplier"
down_revision: str = "0011_document_ocr_langs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bom_items",
        sa.Column("selected_supplier_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_bom_items_selected_supplier",
        "bom_items",
        "suppliers",
        ["selected_supplier_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_bom_items_selected_supplier", "bom_items", type_="foreignkey"
    )
    op.drop_column("bom_items", "selected_supplier_id")
