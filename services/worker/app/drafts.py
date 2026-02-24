from __future__ import annotations

from typing import Any

PROOF_KEYS = (
    "url",
    "source_page",
    "source_pages_sample",
    "status",
    "error",
    "cert_error",
    "redirect_chain",
    "lighthouse_summary",
    "seo_signals",
    "contact_signals",
)


def extract_issue_proof(details: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(details, dict):
        return {}
    proof: dict[str, Any] = {}
    for key in PROOF_KEYS:
        value = details.get(key)
        if value in (None, "", [], {}):
            continue
        proof[key] = value
    return proof


def has_issue_proof(details: dict[str, Any] | None) -> bool:
    return bool(extract_issue_proof(details))


def build_claims_used(issues: list[Any], *, max_items: int = 3) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for issue in issues:
        issue_id = str(getattr(issue, "id", "") or "")
        if not issue_id:
            continue
        proof = extract_issue_proof(getattr(issue, "details", None) or {})
        if not proof:
            continue
        claims.append(
            {
                "issue_id": issue_id,
                "kind": getattr(issue, "kind", None),
                "title": getattr(issue, "title", None),
                "proof": proof,
            }
        )
        if len(claims) >= max_items:
            break
    return claims


def sanitize_claims_used(raw_claims: list[Any], issues: list[Any], *, fallback_max_items: int = 3) -> list[dict[str, Any]]:
    issue_by_id: dict[str, Any] = {}
    for issue in issues:
        issue_id = str(getattr(issue, "id", "") or "")
        if not issue_id or issue_id in issue_by_id:
            continue
        if not has_issue_proof(getattr(issue, "details", None) or {}):
            continue
        issue_by_id[issue_id] = issue

    sanitized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in raw_claims or []:
        issue_id = None
        if isinstance(item, dict):
            candidate = item.get("issue_id") or item.get("id")
            if isinstance(candidate, str):
                issue_id = candidate
        elif isinstance(item, str):
            issue_id = item
        if not issue_id or issue_id in seen_ids:
            continue
        issue = issue_by_id.get(issue_id)
        if issue is None:
            continue
        sanitized.extend(build_claims_used([issue], max_items=1))
        seen_ids.add(issue_id)

    if sanitized:
        return sanitized
    ordered = [issue_by_id[key] for key in issue_by_id]
    return build_claims_used(ordered, max_items=fallback_max_items)
