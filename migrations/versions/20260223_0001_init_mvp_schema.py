"""init mvp schema

Revision ID: 20260223_0001
Revises: None
Create Date: 2026-02-23 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260223_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("place_id", sa.String(length=255), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("phone", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False, server_default=sa.text("'Discovered'")),
        sa.Column("notion_page_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_leads_place_id", "leads", ["place_id"])

    op.create_table(
        "audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("https_ok", sa.Boolean(), nullable=True),
        sa.Column("redirect_chain", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("cert_error", sa.Text(), nullable=True),
        sa.Column("lighthouse_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("crawl_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("contact_signals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("artifact_index", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_audits_lead_id", "audits", ["lead_id"])

    op.create_table(
        "issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("audits.id"), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_issues_audit_id", "issues", ["audit_id"])

    op.create_table(
        "email_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("audits.id"), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gmail_draft_id", sa.String(length=255), nullable=True),
        sa.Column("gmail_draft_url", sa.Text(), nullable=True),
    )
    op.create_index("ix_email_drafts_lead_id", "email_drafts", ["lead_id"])
    op.create_index("ix_email_drafts_audit_id", "email_drafts", ["audit_id"])

    op.create_table(
        "outreach_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_outreach_events_lead_id", "outreach_events", ["lead_id"])

    op.create_table(
        "suppression",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email_or_domain", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("email_or_domain", name="uq_suppression_email_or_domain"),
    )
    op.create_index("ix_suppression_email_or_domain", "suppression", ["email_or_domain"])


def downgrade() -> None:
    op.drop_index("ix_suppression_email_or_domain", table_name="suppression")
    op.drop_table("suppression")
    op.drop_index("ix_outreach_events_lead_id", table_name="outreach_events")
    op.drop_table("outreach_events")
    op.drop_index("ix_email_drafts_audit_id", table_name="email_drafts")
    op.drop_index("ix_email_drafts_lead_id", table_name="email_drafts")
    op.drop_table("email_drafts")
    op.drop_index("ix_issues_audit_id", table_name="issues")
    op.drop_table("issues")
    op.drop_index("ix_audits_lead_id", table_name="audits")
    op.drop_table("audits")
    op.drop_index("ix_leads_place_id", table_name="leads")
    op.drop_table("leads")

