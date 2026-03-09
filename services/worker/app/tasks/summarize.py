from __future__ import annotations

from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import func, select

from app.drafts import build_claims_used, extract_issue_proof, has_issue_proof, sanitize_claims_used
from app.llm.openai_client import generate_draft_with_openai
from app.llm.schemas import DraftOutput, QuickWin
from app.models import Audit, EmailDraft, Issue, Lead, OutreachEvent, Suppression
from app.settings import get_settings
from app.db import SessionLocal
from app.tasks.task_failures import log_task_failure_for_lead
from app.worker import celery_app


def _lead_domain(website_url: str | None) -> str | None:
    if not website_url:
        return None
    normalized_url = website_url.strip()
    if not normalized_url:
        return None
    parsed = urlparse(normalized_url if "://" in normalized_url else f"https://{normalized_url}")
    return parsed.netloc.strip().lower() or None


def _is_suppressed(session, lead: Lead) -> bool:
    values = []
    if lead.email:
        normalized_email = lead.email.strip().lower()
        if normalized_email:
            values.append(normalized_email)
    domain = (lead.website_domain or "").strip().lower() or _lead_domain(lead.website_url)
    if domain:
        values.append(domain)
    if not values:
        return False
    row = session.execute(
        select(Suppression).where(func.lower(func.trim(func.coalesce(Suppression.email_or_domain, ""))).in_(values))
    ).scalar_one_or_none()
    return row is not None


def _quick_win_from_issue(issue: Issue) -> QuickWin:
    details = issue.details or {}
    if issue.kind == "broken_link":
        url = details.get("url", "a broken link")
        source = details.get("source_page", "a page")
        return QuickWin(
            title="Repair broken link",
            why_it_matters=f"Visitors and search engines hit errors from {source}.",
            how_to_fix=f"Update or remove the broken link target ({url}) and retest.",
        )
    if issue.kind == "cert":
        cert_error = details.get("cert_error")
        if cert_error:
            return QuickWin(
                title="Fix TLS certificate issue",
                why_it_matters="Certificate errors reduce trust and can block access.",
                how_to_fix=f"Renew/reconfigure certificate ({cert_error}) and verify HTTPS loads cleanly.",
            )
        return QuickWin(
            title="Redirect HTTP to HTTPS",
            why_it_matters="A single canonical HTTPS experience improves trust and SEO consistency.",
            how_to_fix="Add a server-level 301 redirect from all HTTP requests to HTTPS.",
        )
    return QuickWin(
        title="Fix audit issue",
        why_it_matters=issue.title,
        how_to_fix="Review the cited page and apply the smallest reliable fix first.",
    )


def _serialize_issue_for_llm(issue: Issue) -> dict[str, object]:
    return {
        "id": str(issue.id),
        "kind": issue.kind,
        "severity": issue.severity,
        "title": issue.title,
        "proof": extract_issue_proof(issue.details or {}),
    }


def _audit_payload_for_llm(lead: Lead, audit: Audit, issues: list[Issue], settings) -> dict[str, object]:
    proof_backed_issues = [issue for issue in issues if has_issue_proof(issue.details or {})]
    return {
        "lead": {
            "name": lead.name,
            "category": lead.category,
            "website_url": lead.website_url,
        },
        "audit": {
            "final_url": audit.final_url,
            "https_ok": audit.https_ok,
            "cert_error": audit.cert_error,
            "crawl_summary": audit.crawl_summary,
            "contact_signals": audit.contact_signals,
            "lighthouse_summary": (audit.lighthouse_summary or {}).get("summary")
            if isinstance(audit.lighthouse_summary, dict)
            else None,
        },
        "issues": [_serialize_issue_for_llm(issue) for issue in proof_backed_issues[:20]],
        "email_constraints": {
            "max_words": 150,
            "one_cta": True,
            "sender_name": settings.sender_name,
            "sender_email": settings.sender_email,
            "physical_address": settings.physical_address,
            "opt_out_instructions": settings.opt_out_instructions,
        },
    }


def _build_fallback_draft(lead: Lead, audit: Audit, issues: list[Issue], settings) -> DraftOutput:
    proof_backed_issues = [issue for issue in issues if has_issue_proof(issue.details or {})]
    top_issues = sorted(proof_backed_issues, key=lambda item: item.severity, reverse=True)[:3]
    quick_wins = [_quick_win_from_issue(issue) for issue in top_issues]
    if not quick_wins:
        quick_wins = [
            QuickWin(
                title="Run a quick homepage cleanup",
                why_it_matters="Small website fixes can improve trust and conversion quickly.",
                how_to_fix="Start with homepage links, contact visibility, and HTTPS checks.",
            )
        ]

    lead_profile = (
        f"{lead.name} appears to be a {lead.category or 'local business'} site in the Cleveland area. "
        f"We ran an automated homepage/site audit on {audit.final_url or lead.website_url} and captured "
        f"evidence-backed issues (HTTPS/links/contactability). This is an MVP draft and should be reviewed "
        "before sending."
    )
    claims_used = build_claims_used(top_issues, max_items=3)
    subject = f"Quick website fixes for {lead.name}"

    bullets = "\n".join(f"- {win.title}: {win.why_it_matters}" for win in quick_wins[:3])
    body = (
        f"Hi {lead.name},\n\n"
        "I reviewed your website and found a few quick fixes that could improve trust and usability.\n\n"
        f"{bullets}\n\n"
        "If you want, I can send the exact step-by-step fixes (or handle the updates for you).\n\n"
        f"{settings.sender_name}\n"
        f"{settings.sender_email}\n"
        f"{settings.physical_address}\n"
        f"{settings.opt_out_instructions}"
    )

    return DraftOutput(
        lead_profile=lead_profile,
        quick_wins=quick_wins[:3],
        email_subject=subject,
        email_body_text=body,
        claims_used=claims_used,
    )


@celery_app.task(name="summarize_and_draft")
def summarize_and_draft(lead_id: str, audit_id: str) -> dict[str, object]:
    settings = get_settings()
    draft_id: str | None = None

    try:
        try:
            lead_uuid = UUID(lead_id)
        except ValueError as exc:
            raise RuntimeError(f"invalid lead_id: {lead_id}") from exc
        try:
            audit_uuid = UUID(audit_id)
        except ValueError as exc:
            raise RuntimeError(f"invalid audit_id: {audit_id}") from exc

        with SessionLocal() as session:
            lead = session.get(Lead, lead_uuid)
            if lead is None:
                raise RuntimeError(f"lead not found: {lead_id}")
            audit = session.get(Audit, audit_uuid)
            if audit is None or audit.lead_id != lead.id:
                raise RuntimeError(f"audit not found for lead: {audit_id}")

            if _is_suppressed(session, lead):
                lead.status = "Suppressed"
                session.commit()
                return {"status": "suppressed", "lead_id": lead_id, "audit_id": audit_id}

            issues = (
                session.execute(select(Issue).where(Issue.audit_id == audit.id).order_by(Issue.severity.desc()))
                .scalars()
                .all()
            )
            llm_mode = "fallback"
            llm_error = None
            draft_output: DraftOutput
            if settings.openai_api_key and settings.openai_model:
                try:
                    draft_output = generate_draft_with_openai(
                        api_key=settings.openai_api_key,
                        model=settings.openai_model,
                        base_url=settings.openai_base_url,
                        lead_name=lead.name,
                        audit_payload=_audit_payload_for_llm(lead, audit, issues, settings),
                    )
                    draft_output.claims_used = sanitize_claims_used(draft_output.claims_used, issues)
                    llm_mode = "openai"
                except Exception as exc:  # noqa: BLE001
                    llm_error = str(exc)
                    draft_output = _build_fallback_draft(lead, audit, issues, settings)
            else:
                draft_output = _build_fallback_draft(lead, audit, issues, settings)

            draft = EmailDraft(
                lead_id=lead.id,
                audit_id=audit.id,
                subject=draft_output.email_subject,
                body_text=draft_output.email_body_text,
            )
            session.add(draft)
            lead.status = "Draft Ready"
            session.add(
                OutreachEvent(
                    lead_id=lead.id,
                    type="draft_generated",
                    payload={
                        "draft_id": None,  # filled after refresh below if needed
                        "audit_id": str(audit.id),
                        "llm_mode": llm_mode,
                        "llm_error": llm_error,
                        "claims_used_count": len(draft_output.claims_used),
                    },
                )
            )
            session.commit()
            session.refresh(draft)
            draft_id = str(draft.id)
            # Add a follow-up event with the persisted draft_id to make querying simple.
            session.add(
                OutreachEvent(
                    lead_id=lead.id,
                    type="draft_persisted",
                    payload={"draft_id": draft_id, "audit_id": str(audit.id), "llm_mode": llm_mode},
                )
            )
            session.commit()

        celery_app.send_task("sync_notion", kwargs={"lead_id": lead_id, "audit_id": audit_id, "draft_id": draft_id})
        celery_app.send_task("create_gmail_draft", kwargs={"draft_id": draft_id})

        return {
            "status": "ok",
            "lead_id": lead_id,
            "audit_id": audit_id,
            "draft_id": draft_id,
            "claims_used_count": len(draft_output.claims_used),
            "llm_mode": llm_mode,
            "llm_error": llm_error,
        }
    except Exception as exc:  # noqa: BLE001
        log_task_failure_for_lead(
            lead_id=lead_id,
            task_name="summarize_and_draft",
            error=exc,
            context={"audit_id": audit_id, "draft_id": draft_id},
        )
        raise
