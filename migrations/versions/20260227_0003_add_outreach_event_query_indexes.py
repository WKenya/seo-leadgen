"""add outreach event query indexes

Revision ID: 20260227_0003
Revises: 20260224_0002
Create Date: 2026-02-27 00:03:00
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260227_0003"
down_revision = "20260224_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_outreach_events_created_at", "outreach_events", ["created_at"])
    op.create_index("ix_outreach_events_lead_id_created_at", "outreach_events", ["lead_id", "created_at"])
    op.create_index("ix_outreach_events_type_created_at", "outreach_events", ["type", "created_at"])
    op.drop_index("ix_outreach_events_lead_id", table_name="outreach_events")


def downgrade() -> None:
    op.create_index("ix_outreach_events_lead_id", "outreach_events", ["lead_id"])
    op.drop_index("ix_outreach_events_type_created_at", table_name="outreach_events")
    op.drop_index("ix_outreach_events_lead_id_created_at", table_name="outreach_events")
    op.drop_index("ix_outreach_events_created_at", table_name="outreach_events")
