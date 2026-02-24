from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete

from app.audit.crawler import CrawlConfig, crawl_site
from app.audit.extract import choose_preferred_email
from app.audit.lighthouse_client import normalize_lighthouse_summary, run_lighthouse
from app.audit.screenshots import capture_homepage_screenshot
from app.audit.tls_check import check_tls
from app.db import SessionLocal
from app.models import Audit, Issue, Lead
from app.settings import get_settings
from app.worker import celery_app


@celery_app.task(name="audit_lead")
def audit_lead(lead_id: str) -> dict[str, object]:
    settings = get_settings()
    lead_uuid = UUID(lead_id)

    with SessionLocal() as session:
        lead = session.get(Lead, lead_uuid)
        if lead is None:
            raise RuntimeError(f"lead not found: {lead_id}")
        if not lead.website_url:
            raise RuntimeError(f"lead missing website_url: {lead_id}")

        audit = Audit(lead_id=lead.id, started_at=datetime.now(timezone.utc))
        session.add(audit)
        session.flush()

        tls_result = check_tls(lead.website_url)
        audit_target_url = tls_result.get("final_url") or lead.website_url
        crawl_result = crawl_site(
            audit_target_url,
            CrawlConfig(
                max_pages=settings.crawl_max_pages,
                delay_seconds=settings.crawl_delay_seconds,
                respect_robots=True,
            ),
        )
        lighthouse_result = None
        lighthouse_error = None
        try:
            lighthouse_result = run_lighthouse(settings.audit_lighthouse_url, audit_target_url)
        except Exception as exc:  # noqa: BLE001
            lighthouse_error = str(exc)
        lighthouse_summary = normalize_lighthouse_summary(lighthouse_result) if lighthouse_result else None

        screenshot_result = None
        try:
            screenshot_result = capture_homepage_screenshot(audit_target_url)
        except Exception as exc:  # noqa: BLE001
            screenshot_result = {"status": "error", "error": str(exc), "artifact_path": None}

        audit.final_url = tls_result.get("final_url")
        audit.https_ok = tls_result.get("https_ok")
        audit.redirect_chain = tls_result.get("redirect_chain")
        audit.cert_error = tls_result.get("cert_error")
        audit.lighthouse_summary = (
            {
                "summary": lighthouse_summary,
                "error": lighthouse_error,
                "raw": lighthouse_result if lighthouse_result is not None else None,
            }
            if (lighthouse_result is not None or lighthouse_error)
            else None
        )
        audit.crawl_summary = {
            "visited_pages": crawl_result.get("visited_pages"),
            "checked_links": crawl_result.get("checked_links"),
            "broken_links_count": crawl_result.get("broken_links_count"),
            "seo_signals": crawl_result.get("seo_signals"),
        }
        audit.contact_signals = crawl_result.get("contact_signals")
        audit.artifact_index = {"screenshot": screenshot_result} if screenshot_result is not None else None
        audit.finished_at = datetime.now(timezone.utc)

        session.execute(delete(Issue).where(Issue.audit_id == audit.id))

        severity = 4
        if tls_result.get("cert_error"):
            session.add(
                Issue(
                    audit_id=audit.id,
                    kind="cert",
                    severity=5,
                    title="TLS/certificate issue detected",
                    details={
                        "cert_error": tls_result.get("cert_error"),
                        "final_url": tls_result.get("final_url"),
                        "redirect_chain": tls_result.get("redirect_chain"),
                    },
                )
            )
        elif not tls_result.get("http_to_https"):
            session.add(
                Issue(
                    audit_id=audit.id,
                    kind="cert",
                    severity=3,
                    title="HTTP does not redirect to HTTPS",
                    details={"redirect_chain": tls_result.get("redirect_chain")},
                )
            )

        for broken in (crawl_result.get("broken_links") or [])[:50]:
            session.add(
                Issue(
                    audit_id=audit.id,
                    kind="broken_link",
                    severity=severity,
                    title=f"Broken link: {broken.get('url')}",
                    details=broken,
                )
            )
        if lighthouse_error:
            session.add(
                Issue(
                    audit_id=audit.id,
                    kind="perf",
                    severity=2,
                    title="Lighthouse snapshot failed",
                    details={"error": lighthouse_error, "url": audit_target_url},
                )
            )
        elif lighthouse_summary:
            perf_score = lighthouse_summary.get("performance_score")
            seo_score = lighthouse_summary.get("seo_score")
            if isinstance(perf_score, int) and perf_score < 70:
                session.add(
                    Issue(
                        audit_id=audit.id,
                        kind="perf",
                        severity=3 if perf_score >= 50 else 4,
                        title=f"Low Lighthouse performance score ({perf_score})",
                        details={"url": audit_target_url, "lighthouse_summary": lighthouse_summary},
                    )
                )
            if isinstance(seo_score, int) and seo_score < 80:
                session.add(
                    Issue(
                        audit_id=audit.id,
                        kind="seo",
                        severity=2,
                        title=f"Lighthouse SEO score can improve ({seo_score})",
                        details={"url": audit_target_url, "lighthouse_summary": lighthouse_summary},
                    )
                )

        contact_signals = crawl_result.get("contact_signals") or {}
        seo_signals = crawl_result.get("seo_signals") or {}
        preferred_email = choose_preferred_email(contact_signals.get("emails_found") or [])
        if preferred_email and not lead.email:
            lead.email = preferred_email
        if not contact_signals.get("has_contact_page"):
            session.add(
                Issue(
                    audit_id=audit.id,
                    kind="contact",
                    severity=3,
                    title="No contact page detected",
                    details={"url": audit_target_url, "contact_signals": contact_signals},
                )
            )
        if not contact_signals.get("has_mailto") and not contact_signals.get("emails_found"):
            session.add(
                Issue(
                    audit_id=audit.id,
                    kind="contact",
                    severity=2,
                    title="No email contact found in crawl",
                    details={"url": audit_target_url, "contact_signals": contact_signals},
                )
            )
        if not seo_signals.get("title_present"):
            session.add(
                Issue(
                    audit_id=audit.id,
                    kind="seo",
                    severity=3,
                    title="Missing title tag on audited homepage",
                    details={"url": audit_target_url, "seo_signals": seo_signals},
                )
            )
        if not seo_signals.get("meta_description_present"):
            session.add(
                Issue(
                    audit_id=audit.id,
                    kind="seo",
                    severity=2,
                    title="Missing meta description on audited homepage",
                    details={"url": audit_target_url, "seo_signals": seo_signals},
                )
            )
        if seo_signals.get("robots_noindex"):
            session.add(
                Issue(
                    audit_id=audit.id,
                    kind="seo",
                    severity=4,
                    title="Homepage robots meta includes noindex",
                    details={"url": audit_target_url, "seo_signals": seo_signals},
                )
            )

        lead.status = "Audited"
        session.commit()
        audit_id_value = str(audit.id)
        lead_email_value = lead.email

    celery_app.send_task("summarize_and_draft", kwargs={"lead_id": lead_id, "audit_id": audit_id_value})

    return {
        "status": "ok",
        "lead_id": lead_id,
        "audit_id": audit_id_value,
        "https_ok": tls_result.get("https_ok"),
        "cert_error": tls_result.get("cert_error"),
        "broken_links_count": crawl_result.get("broken_links_count"),
        "visited_pages": crawl_result.get("visited_pages"),
        "lighthouse_error": lighthouse_error,
        "lighthouse_summary": lighthouse_summary,
        "lead_email": lead_email_value,
        "seo_signals": seo_signals,
    }
