from __future__ import annotations

import sys
from pathlib import Path
import unittest

WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from app.audit.lighthouse_client import normalize_lighthouse_summary  # noqa: E402


class LighthouseClientTests(unittest.TestCase):
    def test_normalize_stub_summary_shape(self) -> None:
        payload = {
            "ok": True,
            "summary": {
                "performance_score": 0.62,
                "seo_score": 91,
                "lcp_ms": 3100,
                "cls": 0.03,
                "inp_ms": 180,
            },
        }
        got = normalize_lighthouse_summary(payload)
        self.assertIsNotNone(got)
        self.assertEqual(got["performance_score"], 62)
        self.assertEqual(got["seo_score"], 91)
        self.assertEqual(got["lcp_ms"], 3100)
        self.assertEqual(got["source"], "audit_service_summary")

    def test_normalize_raw_lighthouse_shape(self) -> None:
        payload = {
            "categories": {
                "performance": {"score": 0.48},
                "seo": {"score": 0.87},
            },
            "audits": {
                "largest-contentful-paint": {"numericValue": 4100},
                "cumulative-layout-shift": {"numericValue": 0.18},
                "interaction-to-next-paint": {"numericValue": 260},
                "total-blocking-time": {"numericValue": 420},
            },
        }
        got = normalize_lighthouse_summary(payload)
        self.assertIsNotNone(got)
        self.assertEqual(got["performance_score"], 48)
        self.assertEqual(got["seo_score"], 87)
        self.assertEqual(got["lcp_ms"], 4100)
        self.assertEqual(got["tbt_ms"], 420)
        self.assertEqual(got["source"], "lighthouse_raw")


if __name__ == "__main__":
    unittest.main()

