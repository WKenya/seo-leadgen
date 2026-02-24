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
