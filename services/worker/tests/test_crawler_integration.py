from __future__ import annotations

import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.audit.crawler import CrawlConfig, crawl_site


class _FixtureSiteHandler(BaseHTTPRequestHandler):
    def _route(self) -> tuple[int, str]:
        if self.path == "/":
            return (
                200,
                (
                    "<html><head><title>Fixture Site</title></head><body>"
                    '<a href="/ok">ok</a>'
                    '<a href="/missing">missing</a>'
                    '<a href="mailto:owner@example.com">email</a>'
                    "</body></html>"
                ),
            )
        if self.path == "/ok":
            return (200, "<html><body>OK</body></html>")
        if self.path == "/missing":
            return (404, "<html><body>Missing</body></html>")
        if self.path == "/robots.txt":
            return (200, "User-agent: *\nAllow: /\n")
        return (404, "<html><body>Missing</body></html>")

    def do_HEAD(self) -> None:  # noqa: N802
        status, _ = self._route()
        self.send_response(status)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        status, body = self._route()
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        del fmt, args
        return


class CrawlerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls._server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureSiteHandler)
        except PermissionError as exc:
            raise unittest.SkipTest(f"socket bind not permitted in this environment: {exc}") from exc
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()
        host, port = cls._server.server_address
        cls._base_url = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.shutdown()
        cls._server.server_close()
        cls._thread.join(timeout=2)

    def test_crawl_site_detects_intentional_404(self) -> None:
        result = crawl_site(
            f"{self._base_url}/",
            CrawlConfig(max_pages=5, delay_seconds=0.0, respect_robots=False),
        )

        self.assertGreaterEqual(int(result["visited_pages"]), 2)
        self.assertGreaterEqual(int(result["checked_links"]), 2)
        self.assertGreaterEqual(int(result["broken_links_count"]), 1)

        broken_urls = {str(item.get("url")) for item in (result.get("broken_links") or [])}
        self.assertIn(f"{self._base_url}/missing", broken_urls)

        contact_signals = result.get("contact_signals") or {}
        self.assertTrue(contact_signals.get("has_mailto"))

        seo_signals = result.get("seo_signals") or {}
        self.assertTrue(seo_signals.get("title_present"))


if __name__ == "__main__":
    unittest.main()
