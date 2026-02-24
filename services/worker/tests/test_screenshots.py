from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path
import unittest

WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from app.audit.screenshots import build_screenshot_relpath  # noqa: E402


class ScreenshotTests(unittest.TestCase):
    def test_build_screenshot_relpath_uses_host_and_timestamp(self) -> None:
        now = datetime(2026, 2, 24, 12, 34, 56, tzinfo=timezone.utc)
        rel = build_screenshot_relpath("https://WWW.Example.com/path?q=1", now=now)
        self.assertEqual(rel, "screenshots/www.example.com/20260224T123456Z.png")

    def test_build_screenshot_relpath_handles_missing_host(self) -> None:
        rel = build_screenshot_relpath("not-a-url", now=datetime(2026, 2, 24, tzinfo=timezone.utc))
        self.assertTrue(rel.startswith("screenshots/unknown/"))


if __name__ == "__main__":
    unittest.main()

