from __future__ import annotations

import sys
from pathlib import Path
import unittest

WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from app.drafts import extract_issue_proof, has_issue_proof  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
