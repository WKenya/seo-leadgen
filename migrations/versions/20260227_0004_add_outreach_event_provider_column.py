"""add outreach event provider column

Revision ID: 20260227_0004
Revises: 20260227_0003
Create Date: 2026-02-27 00:04:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260227_0004"
down_revision = "20260227_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outreach_events", sa.Column("provider", sa.String(length=64), nullable=True))
    op.execute(
        """
        UPDATE outreach_events
        SET provider = lower(nullif(trim(payload ->> 'provider'), ''))
        WHERE provider IS NULL
          AND payload IS NOT NULL
          AND jsonb_typeof(payload) = 'object'
        """
    )
    op.create_index("ix_outreach_events_provider", "outreach_events", ["provider"])
    op.create_index("ix_outreach_events_provider_created_at", "outreach_events", ["provider", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_outreach_events_provider_created_at", table_name="outreach_events")
    op.drop_index("ix_outreach_events_provider", table_name="outreach_events")
    op.drop_column("outreach_events", "provider")
