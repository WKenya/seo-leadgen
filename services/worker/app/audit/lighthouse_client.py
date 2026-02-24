from __future__ import annotations

from typing import Any

import httpx


def run_lighthouse(audit_service_url: str, url: str) -> dict[str, object]:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(audit_service_url, json={"url": url})
        response.raise_for_status()
        return response.json()


def _score_to_100(value: Any) -> int | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 1.0:
        numeric *= 100.0
    return int(round(numeric))


def normalize_lighthouse_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None

    # Stub / microservice normalized shape: {summary: {...}}
    summary = payload.get("summary")
    if isinstance(summary, dict):
        return {
            "performance_score": _score_to_100(summary.get("performance_score")),
            "seo_score": _score_to_100(summary.get("seo_score")),
            "lcp_ms": summary.get("lcp_ms"),
            "cls": summary.get("cls"),
            "inp_ms": summary.get("inp_ms"),
            "tbt_ms": summary.get("tbt_ms"),
            "source": "audit_service_summary",
        }

    # Raw Lighthouse shape fallback.
    lhr = payload.get("lhr") if isinstance(payload.get("lhr"), dict) else payload
    if not isinstance(lhr, dict):
        return None
    categories = lhr.get("categories") or {}
    audits = lhr.get("audits") or {}

    def audit_num(audit_id: str) -> float | int | None:
        node = audits.get(audit_id)
        if not isinstance(node, dict):
            return None
        value = node.get("numericValue")
        return value if isinstance(value, (int, float)) else None

    return {
        "performance_score": _score_to_100((categories.get("performance") or {}).get("score")),
        "seo_score": _score_to_100((categories.get("seo") or {}).get("score")),
        "lcp_ms": audit_num("largest-contentful-paint"),
        "cls": audit_num("cumulative-layout-shift"),
        "inp_ms": audit_num("interaction-to-next-paint"),
        "tbt_ms": audit_num("total-blocking-time"),
        "source": "lighthouse_raw",
    }
