from __future__ import annotations

import sys
from pathlib import Path
import unittest

WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from app.audit.issues import aggregate_broken_links  # noqa: E402


class AuditIssuesTests(unittest.TestCase):
    def test_aggregate_broken_links_groups_duplicates(self) -> None:
        rows = [
            {"url": "https://x.test/a", "status": 404, "source_page": "https://x.test/1"},
            {"url": "https://x.test/a", "status": 404, "source_page": "https://x.test/2"},
            {"url": "https://x.test/b", "status": 500, "source_page": "https://x.test/1"},
        ]
        grouped = aggregate_broken_links(rows, max_groups=10)
        self.assertEqual(len(grouped), 2)
        self.assertEqual(grouped[0]["url"], "https://x.test/a")
        self.assertEqual(grouped[0]["occurrences"], 2)
        self.assertEqual(grouped[0]["source_pages_sample"], ["https://x.test/1", "https://x.test/2"])

    def test_aggregate_broken_links_caps_groups(self) -> None:
        rows = [{"url": f"https://x.test/{i}", "status": 404, "source_page": "https://x.test"} for i in range(5)]
        grouped = aggregate_broken_links(rows, max_groups=3)
        self.assertEqual(len(grouped), 3)


if __name__ == "__main__":
    unittest.main()

