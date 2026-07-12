"""Sell-side quotation generator: quotations tables + project defaults.

Revision ID: 0010_quotations
Revises: 0009_bom_hs_code
Create Date: 2026-07-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_quotations"
down_revision: str = "0009_bom_hs_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_uuid = postgresql.UUID(as_uuid=True)


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
    # Sell-side quotation defaults on projects.
    op.add_column(
        "projects",
        sa.Column(
            "margin_pct", sa.Numeric(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "gst_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "gst_pct", sa.Numeric(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "terms",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "quotations",
        sa.Column(
            "id", _uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "project_id",
            _uuid,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("quote_no", sa.String(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        *_timestamps(),
        sa.UniqueConstraint(
            "project_id", "quote_no", name="uq_quotations_project_quote_no"
        ),
    )
    op.create_index(
        "ix_quotations_project", "quotations", ["project_id"]
    )

    op.create_table(
        "quotation_versions",
        sa.Column(
            "id", _uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "quotation_id",
            _uuid,
            sa.ForeignKey("quotations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(), nullable=False, server_default="USD"),
        sa.Column("margin_pct", sa.Numeric(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "gst_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("gst_pct", sa.Numeric(), nullable=False, server_default=sa.text("0")),
        sa.Column("validity_days", sa.Integer(), nullable=True),
        sa.Column(
            "terms_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("subtotal", sa.Numeric(), nullable=True),
        sa.Column("tax_total", sa.Numeric(), nullable=True),
        sa.Column("grand_total", sa.Numeric(), nullable=True),
        sa.Column("docx_key", sa.String(), nullable=True),
        sa.Column("xlsx_key", sa.String(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "quotation_id", "version_no", name="uq_quotation_versions_no"
        ),
    )
    op.create_index(
        "ix_quotation_versions_quotation",
        "quotation_versions",
        ["quotation_id"],
    )

    op.create_table(
        "quotation_lines",
        sa.Column(
            "id", _uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "version_id",
            _uuid,
            sa.ForeignKey("quotation_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("spec", sa.Text(), nullable=True),
        sa.Column("qty", sa.Numeric(), nullable=True),
        sa.Column("unit_cost", sa.Numeric(), nullable=True),
        sa.Column("cost_source", sa.String(), nullable=True),
        sa.Column("unit_price", sa.Numeric(), nullable=True),
        sa.Column("line_total", sa.Numeric(), nullable=True),
        sa.Column(
            "gap_flag", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        *_timestamps(),
    )
    op.create_index(
        "ix_quotation_lines_version", "quotation_lines", ["version_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_quotation_lines_version", table_name="quotation_lines")
    op.drop_table("quotation_lines")
    op.drop_index(
        "ix_quotation_versions_quotation", table_name="quotation_versions"
    )
    op.drop_table("quotation_versions")
    op.drop_index("ix_quotations_project", table_name="quotations")
    op.drop_table("quotations")
    op.drop_column("projects", "terms")
    op.drop_column("projects", "gst_pct")
    op.drop_column("projects", "gst_enabled")
    op.drop_column("projects", "margin_pct")
