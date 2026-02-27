from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.utcnow()


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    place_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    website_url: Mapped[str] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="Discovered")
    notion_page_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    audits: Mapped[list[Audit]] = relationship(back_populates="lead")


class Audit(Base):
    __tablename__ = "audits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id"), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    https_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    redirect_chain: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    cert_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    lighthouse_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    crawl_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    contact_signals: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    artifact_index: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    lead: Mapped[Lead] = relationship(back_populates="audits")
    issues: Mapped[list[Issue]] = relationship(back_populates="audit")


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audits.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    severity: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    audit: Mapped[Audit] = relationship(back_populates="issues")


class EmailDraft(Base):
    __tablename__ = "email_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id"), index=True)
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("audits.id"), index=True)
    subject: Mapped[str] = mapped_column(Text)
    body_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gmail_draft_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gmail_draft_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class OutreachEvent(Base):
    __tablename__ = "outreach_events"
    __table_args__ = (
        Index("ix_outreach_events_created_at", "created_at"),
        Index("ix_outreach_events_lead_id_created_at", "lead_id", "created_at"),
        Index("ix_outreach_events_type_created_at", "type", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lead_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("leads.id"))
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True, unique=True)
    type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Suppression(Base):
    __tablename__ = "suppression"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_or_domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    reason: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
