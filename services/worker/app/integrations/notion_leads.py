from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models import Audit, EmailDraft, Lead


def _rich_text(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    return [{"type": "text", "text": {"content": value[:2000]}}]


REQUIRED_NOTION_PROPERTIES = {
    "Name",
    "Status",
    "Category",
    "Source",
    "Website",
    "Email",
    "Phone",
    "Address",
    "Findings",
    "Proof",
    "Email Draft",
    "Gmail Draft Link",
    "Opt-out",
}


def lead_page_properties(
    *,
    lead: Lead,
    audit: Audit | None = None,
    draft: EmailDraft | None = None,
) -> dict[str, Any]:
    findings_lines: list[str] = []
    proof_url = None
    if audit:
        if audit.cert_error:
            findings_lines.append(f"TLS/cert issue: {audit.cert_error}")
        if audit.crawl_summary:
            broken_count = audit.crawl_summary.get("broken_links_count")
            if broken_count:
                findings_lines.append(f"Broken links found: {broken_count}")
        if audit.contact_signals and not audit.contact_signals.get("has_contact_page"):
            findings_lines.append("No contact page detected")
    if draft:
        draft_preview = draft.body_text[:1800]
    else:
        draft_preview = None

    props: dict[str, Any] = {
        "Name": {"title": _rich_text(lead.name)},
        "Status": {"select": {"name": lead.status}},
        "Category": {"select": {"name": lead.category or "Uncategorized"}},
        "Source": {"select": {"name": lead.source or "unknown"}},
        "Website": {"url": lead.website_url},
        "Email": {"email": lead.email},
        "Phone": {"rich_text": _rich_text(lead.phone)},
        "Address": {"rich_text": _rich_text(lead.address)},
        "Findings": {"rich_text": _rich_text("\n".join(findings_lines) if findings_lines else None)},
        "Proof": {"rich_text": _rich_text(proof_url)},
        "Email Draft": {"rich_text": _rich_text(draft_preview)},
        "Gmail Draft Link": {"url": draft.gmail_draft_url if draft else None},
        "Opt-out": {"checkbox": lead.status == "Suppressed"},
    }
    return props


class NotionLeadSyncClient:
    def __init__(self, token: str, database_id: str) -> None:
        from notion_client import Client  # lazy import

        self.database_id = database_id
        self.client = Client(auth=token)

    def get_database_property_names(self) -> set[str]:
        database = self.client.databases.retrieve(database_id=self.database_id)
        properties = database.get("properties") or {}
        return set(properties.keys())

    def upsert_lead_page(
        self,
        *,
        lead: Lead,
        audit: Audit | None = None,
        draft: EmailDraft | None = None,
    ) -> str:
        properties = lead_page_properties(lead=lead, audit=audit, draft=draft)
        available = self.get_database_property_names()
        missing = REQUIRED_NOTION_PROPERTIES - available
        if missing:
            raise RuntimeError(f"notion_missing_properties: {sorted(missing)}")
        properties = {key: value for key, value in properties.items() if key in available}
        if lead.notion_page_id:
            self.client.pages.update(page_id=lead.notion_page_id, properties=properties)
            return lead.notion_page_id

        page = self.client.pages.create(parent={"database_id": self.database_id}, properties=properties)
        page_id = page["id"]
        return page_id
