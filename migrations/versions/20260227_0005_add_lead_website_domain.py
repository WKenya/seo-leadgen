"""add lead website_domain

Revision ID: 20260227_0005
Revises: 20260227_0004
Create Date: 2026-02-27 00:05:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260227_0005"
down_revision = "20260227_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("website_domain", sa.String(length=255), nullable=True))
    op.execute(
        """
        UPDATE leads
        SET website_domain = lower(
            nullif(
                regexp_replace(
                    regexp_replace(website_url, '^https?://', '', 'i'),
                    '/.*$',
                    ''
                ),
                ''
            )
        )
        WHERE website_url IS NOT NULL
          AND website_domain IS NULL
        """
    )
    op.create_index("ix_leads_website_domain", "leads", ["website_domain"])


def downgrade() -> None:
    op.drop_index("ix_leads_website_domain", table_name="leads")
    op.drop_column("leads", "website_domain")
