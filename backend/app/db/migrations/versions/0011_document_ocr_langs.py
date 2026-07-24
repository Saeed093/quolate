"""Per-document OCR language selection (chosen at upload).

Revision ID: 0011_document_ocr_langs
Revises: 0010_quotations
Create Date: 2026-07-24
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_document_ocr_langs"
down_revision: str = "0010_quotations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("ocr_langs", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("documents", "ocr_langs")
