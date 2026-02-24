from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Audit, Issue
from app.schemas import AuditRead, IssueRead

router = APIRouter(prefix="/audits", tags=["audits"])


@router.get("/{audit_id}")
def get_audit(audit_id: UUID, db: Session = Depends(get_db)) -> dict[str, object]:
    audit = db.get(Audit, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="audit not found")
    return AuditRead.from_model(audit).model_dump()


@router.get("/{audit_id}/issues")
def list_audit_issues(audit_id: UUID, db: Session = Depends(get_db)) -> dict[str, object]:
    audit = db.get(Audit, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="audit not found")
    issues = (
        db.execute(select(Issue).where(Issue.audit_id == audit_id).order_by(Issue.severity.desc(), Issue.title.asc()))
        .scalars()
        .all()
    )
    return {"items": [IssueRead.from_model(issue).model_dump() for issue in issues]}

