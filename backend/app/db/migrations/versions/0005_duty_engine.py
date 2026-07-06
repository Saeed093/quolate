"""Pakistan duty/tax calculation engine: rates + conditional exemptions.

Revision ID: 0005_duty_engine
Revises: 0004_library_comments
Create Date: 2026-07-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_duty_engine"
down_revision: str = "0004_library_comments"
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
        "duty_tax_rates",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("hs_code", sa.String(length=10), nullable=False),
        sa.Column("levy_type", sa.String(length=10), nullable=False),
        sa.Column("rate_type", sa.String(length=10), nullable=False),
        sa.Column("rate_value", sa.Numeric(12, 6), nullable=True),
        sa.Column("slab_rules", postgresql.JSONB(), nullable=True),
        sa.Column("importer_category", sa.String(length=50), nullable=True),
        sa.Column("atl_status", sa.String(length=10), nullable=True),
        sa.Column("sro_reference", sa.String(length=200), nullable=True),
        sa.Column("legal_reference", sa.String(length=200), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("superseded_by", _uuid, nullable=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="approved"
        ),
        sa.Column("source_document", sa.String(length=300), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["superseded_by"], ["duty_tax_rates.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "levy_type IN ('CD','ACD','RD','ST','FED','WHT_148')",
            name="ck_duty_tax_rates_levy_type",
        ),
        sa.CheckConstraint(
            "rate_type IN ('percent','fixed','slab')",
            name="ck_duty_tax_rates_rate_type",
        ),
        sa.CheckConstraint(
            "atl_status IS NULL OR atl_status IN ('atl','non_atl')",
            name="ck_duty_tax_rates_atl_status",
        ),
        sa.CheckConstraint(
            "status IN ('pending_review','approved','rejected')",
            name="ck_duty_tax_rates_status",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_duty_tax_rates_effective_range",
        ),
    )
    op.create_index(
        "ix_duty_tax_rates_hs_levy_effective",
        "duty_tax_rates",
        ["hs_code", "levy_type", "effective_from"],
    )
    op.create_index(
        "ix_duty_tax_rates_current",
        "duty_tax_rates",
        ["hs_code", "levy_type"],
        postgresql_where=sa.text("effective_to IS NULL AND status = 'approved'"),
    )

    op.create_table(
        "exemption_rules",
        _uuid_pk(),
        *_timestamps(),
        sa.Column("hs_code", sa.String(length=10), nullable=True),
        sa.Column("levy_type", sa.String(length=10), nullable=False),
        sa.Column("importer_category", sa.String(length=50), nullable=True),
        sa.Column("certificate_type", sa.String(length=100), nullable=True),
        sa.Column(
            "requires_certificate",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("exemption_type", sa.String(length=20), nullable=False),
        sa.Column("reduced_rate", sa.Numeric(12, 6), nullable=True),
        sa.Column("condition_description", sa.Text(), nullable=True),
        sa.Column("sro_reference", sa.String(length=200), nullable=True),
        sa.Column("schedule_reference", sa.String(length=100), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="approved"
        ),
        sa.Column("source_document", sa.String(length=300), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "levy_type IN ('CD','ACD','RD','ST','FED','WHT_148')",
            name="ck_exemption_rules_levy_type",
        ),
        sa.CheckConstraint(
            "exemption_type IN ('full','reduced_rate')",
            name="ck_exemption_rules_exemption_type",
        ),
        sa.CheckConstraint(
            "exemption_type <> 'reduced_rate' OR reduced_rate IS NOT NULL",
            name="ck_exemption_rules_reduced_rate_required",
        ),
        sa.CheckConstraint(
            "status IN ('pending_review','approved','rejected')",
            name="ck_exemption_rules_status",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_exemption_rules_effective_range",
        ),
    )
    op.create_index(
        "ix_exemption_rules_hs_levy", "exemption_rules", ["hs_code", "levy_type"]
    )
    op.create_index(
        "ix_exemption_rules_importer_category",
        "exemption_rules",
        ["importer_category"],
    )


def downgrade() -> None:
    op.drop_index("ix_exemption_rules_importer_category", table_name="exemption_rules")
    op.drop_index("ix_exemption_rules_hs_levy", table_name="exemption_rules")
    op.drop_table("exemption_rules")
    op.drop_index("ix_duty_tax_rates_current", table_name="duty_tax_rates")
    op.drop_index("ix_duty_tax_rates_hs_levy_effective", table_name="duty_tax_rates")
    op.drop_table("duty_tax_rates")
