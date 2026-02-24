"""add outreach event external_id

Revision ID: 20260224_0002
Revises: 20260223_0001
Create Date: 2026-02-24 00:02:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260224_0002"
down_revision = "20260223_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outreach_events", sa.Column("external_id", sa.String(length=255), nullable=True))
    op.create_index("ix_outreach_events_external_id", "outreach_events", ["external_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_outreach_events_external_id", table_name="outreach_events")
    op.drop_column("outreach_events", "external_id")

