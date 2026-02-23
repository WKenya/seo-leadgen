from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import EmailDraft


def sent_count_today(session: Session, *, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    stmt = select(func.count()).select_from(EmailDraft).where(EmailDraft.sent_at >= start, EmailDraft.sent_at < end)
    return int(session.execute(stmt).scalar_one())


def remaining_daily_send_cap(session: Session, *, cap: int, now: datetime | None = None) -> int:
    return max(0, cap - sent_count_today(session, now=now))

