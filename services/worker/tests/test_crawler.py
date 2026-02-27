from __future__ import annotations

import unittest
from unittest.mock import patch

from app.audit.crawler import CrawlConfig, crawl_site


class _FakeResponse:
    def __init__(self, url: str, *, status_code: int = 200, text: str = "") -> None:
        self.url = url
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    def __init__(self, pages: dict[str, dict[str, object]]) -> None:
        self._pages = pages
        self.get_calls: list[str] = []
        self.head_calls: list[str] = []

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        return False

    def head(self, url: str, follow_redirects: bool = True) -> _FakeResponse:
        self.head_calls.append(url)
        return _FakeResponse(url, status_code=200, text="")

    def get(self, url: str, follow_redirects: bool = True) -> _FakeResponse:
        self.get_calls.append(url)
        page = self._pages.get(url)
        if page is None:
            return _FakeResponse(url, status_code=404, text="")
        return _FakeResponse(url, status_code=int(page["status_code"]), text=str(page["text"]))


class _FakeRobots:
    def __init__(self, disallowed: set[str]) -> None:
        self.disallowed = disallowed

    def can_fetch(self, user_agent: str, url: str) -> bool:
        del user_agent
        return url not in self.disallowed


class CrawlerRobotsTests(unittest.TestCase):
    def _build_client_factory(
        self, pages: dict[str, dict[str, object]]
    ) -> tuple[dict[str, _FakeClient], object]:
        holder: dict[str, _FakeClient] = {}

        def factory(*args, **kwargs):  # type: ignore[no-untyped-def]
            del args, kwargs
            client = _FakeClient(pages)
            holder["client"] = client
            return client

        return holder, factory

    def test_respect_robots_skips_start_url_when_disallowed(self) -> None:
        start_url = "https://example.com/"
        pages = {
            start_url: {"status_code": 200, "text": '<a href="/allowed">allowed</a>'},
            "https://example.com/allowed": {"status_code": 200, "text": ""},
        }
        holder, fake_client_factory = self._build_client_factory(pages)
        robots = _FakeRobots({start_url})

        with (
            patch("app.audit.crawler._load_robots", return_value=robots),
            patch("app.audit.crawler.httpx.Client", side_effect=fake_client_factory),
            patch("app.audit.crawler.time.sleep", return_value=None),
        ):
            result = crawl_site(start_url, CrawlConfig(max_pages=10, delay_seconds=0.0, respect_robots=True))

        self.assertEqual(result["visited_pages"], 0)
        self.assertEqual(result["checked_links"], 0)
        self.assertEqual(holder["client"].get_calls, [])

    def test_respect_robots_skips_disallowed_internal_links(self) -> None:
        start_url = "https://example.com/"
        allowed_url = "https://example.com/allowed"
        disallowed_url = "https://example.com/private"
        pages = {
            start_url: {
                "status_code": 200,
                "text": '<a href="/allowed">allowed</a><a href="/private">private</a>',
            },
            allowed_url: {"status_code": 200, "text": ""},
        }
        holder, fake_client_factory = self._build_client_factory(pages)
        robots = _FakeRobots({disallowed_url})

        with (
            patch("app.audit.crawler._load_robots", return_value=robots),
            patch("app.audit.crawler.httpx.Client", side_effect=fake_client_factory),
            patch("app.audit.crawler.time.sleep", return_value=None),
        ):
            result = crawl_site(start_url, CrawlConfig(max_pages=10, delay_seconds=0.0, respect_robots=True))

        client = holder["client"]
        self.assertEqual(result["visited_pages"], 2)
        self.assertEqual(result["checked_links"], 1)
        self.assertNotIn(disallowed_url, client.head_calls)
        self.assertNotIn(disallowed_url, client.get_calls)

    def test_disable_robots_allows_internal_disallowed_path(self) -> None:
        start_url = "https://example.com/"
        allowed_url = "https://example.com/allowed"
        disallowed_url = "https://example.com/private"
        pages = {
            start_url: {
                "status_code": 200,
                "text": '<a href="/allowed">allowed</a><a href="/private">private</a>',
            },
            allowed_url: {"status_code": 200, "text": ""},
            disallowed_url: {"status_code": 200, "text": ""},
        }
        holder, fake_client_factory = self._build_client_factory(pages)

        with (
            patch("app.audit.crawler._load_robots") as load_robots_mock,
            patch("app.audit.crawler.httpx.Client", side_effect=fake_client_factory),
            patch("app.audit.crawler.time.sleep", return_value=None),
        ):
            result = crawl_site(start_url, CrawlConfig(max_pages=10, delay_seconds=0.0, respect_robots=False))

        client = holder["client"]
        load_robots_mock.assert_not_called()
        self.assertEqual(result["visited_pages"], 3)
        self.assertEqual(result["checked_links"], 2)
        self.assertIn(disallowed_url, client.head_calls)


if __name__ == "__main__":
    unittest.main()
