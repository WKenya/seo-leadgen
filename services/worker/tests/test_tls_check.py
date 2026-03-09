from __future__ import annotations

import sys
from pathlib import Path
import unittest

WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from app.audit.tls_check import _with_scheme  # noqa: E402


class TlsCheckTests(unittest.TestCase):
    def test_with_scheme_trims_whitespace_around_host_without_scheme(self) -> None:
        self.assertEqual(_with_scheme("  example.com  ", "https"), "https://example.com/")

    def test_with_scheme_trims_whitespace_around_url_with_scheme(self) -> None:
        self.assertEqual(_with_scheme("  https://example.com/path  ", "http"), "http://example.com/path")

    def test_with_scheme_preserves_query(self) -> None:
        self.assertEqual(_with_scheme(" example.com/path?q=1 ", "https"), "https://example.com/path?q=1")


if __name__ == "__main__":
    unittest.main()
