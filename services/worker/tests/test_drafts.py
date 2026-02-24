from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from app.drafts import build_claims_used, extract_issue_proof, has_issue_proof, sanitize_claims_used  # noqa: E402


class DraftProofTests(unittest.TestCase):
    def test_extract_issue_proof_keeps_supported_non_empty_fields(self) -> None:
        details = {
            "url": "https://x.test",
            "source_pages_sample": ["https://x.test/a"],
            "status": 404,
            "contact_signals": {"has_contact_page": False},
            "unknown": "skip",
            "error": "",
        }
        proof = extract_issue_proof(details)
        self.assertEqual(
            proof,
            {
                "url": "https://x.test",
                "source_pages_sample": ["https://x.test/a"],
                "status": 404,
                "contact_signals": {"has_contact_page": False},
            },
        )

    def test_has_issue_proof_false_for_empty_or_unsupported_details(self) -> None:
        self.assertFalse(has_issue_proof(None))
        self.assertFalse(has_issue_proof({"unknown": "value"}))
        self.assertFalse(has_issue_proof({"url": ""}))

    def test_build_claims_used_includes_proof_and_skips_proofless(self) -> None:
        issues = [
            SimpleNamespace(id="1", kind="seo", title="Missing title", details={"url": "https://x.test"}),
            SimpleNamespace(id="2", kind="perf", title="Low perf", details={"unknown": "x"}),
        ]
        claims = build_claims_used(issues, max_items=5)
        self.assertEqual(
            claims,
            [
                {
                    "issue_id": "1",
                    "kind": "seo",
                    "title": "Missing title",
                    "proof": {"url": "https://x.test"},
                }
            ],
        )

    def test_sanitize_claims_used_filters_unknown_and_hydrates_from_issues(self) -> None:
        issues = [
            SimpleNamespace(
                id="a",
                kind="broken_link",
                title="Broken link",
                details={"url": "https://x.test/bad", "status": 404},
            ),
            SimpleNamespace(id="b", kind="seo", title="No title", details={"unknown": "x"}),
        ]
        claims = sanitize_claims_used([{"issue_id": "a"}, {"issue_id": "missing"}, "a", {"id": "b"}], issues)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["issue_id"], "a")
        self.assertEqual(claims[0]["proof"], {"url": "https://x.test/bad", "status": 404})

    def test_sanitize_claims_used_falls_back_to_top_proof_backed_issue(self) -> None:
        issues = [
            SimpleNamespace(id="x", kind="cert", title="TLS", details={"cert_error": "expired"}),
            SimpleNamespace(id="y", kind="seo", title="No title", details={"unknown": "x"}),
        ]
        claims = sanitize_claims_used([], issues)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["issue_id"], "x")
        self.assertEqual(claims[0]["proof"], {"cert_error": "expired"})


if __name__ == "__main__":
    unittest.main()
