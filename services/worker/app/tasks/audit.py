from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete

from app.audit.crawler import CrawlConfig, crawl_site
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
        crawl_result = crawl_site(
            tls_result.get("final_url") or lead.website_url,
            CrawlConfig(
                max_pages=settings.crawl_max_pages,
                delay_seconds=settings.crawl_delay_seconds,
                respect_robots=True,
            ),
        )

        audit.final_url = tls_result.get("final_url")
        audit.https_ok = tls_result.get("https_ok")
        audit.redirect_chain = tls_result.get("redirect_chain")
        audit.cert_error = tls_result.get("cert_error")
        audit.crawl_summary = {
            "visited_pages": crawl_result.get("visited_pages"),
            "checked_links": crawl_result.get("checked_links"),
            "broken_links_count": crawl_result.get("broken_links_count"),
        }
        audit.contact_signals = crawl_result.get("contact_signals")
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

        lead.status = "Audited"
        session.commit()

    return {
        "status": "ok",
        "lead_id": lead_id,
        "https_ok": tls_result.get("https_ok"),
        "cert_error": tls_result.get("cert_error"),
        "broken_links_count": crawl_result.get("broken_links_count"),
        "visited_pages": crawl_result.get("visited_pages"),
    }
