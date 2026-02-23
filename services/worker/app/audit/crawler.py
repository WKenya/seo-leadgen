from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from app.audit.extract import extract_links, find_contact_signals, is_internal_url, normalize_link


@dataclass(slots=True)
class CrawlConfig:
    max_pages: int = 10
    delay_seconds: float = 1.0
    respect_robots: bool = True


def _load_robots(start_url: str) -> RobotFileParser | None:
    parsed = urlparse(start_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
        return parser
    except Exception:  # noqa: BLE001
        return None


def _check_link(client: httpx.Client, url: str) -> tuple[int | None, str | None]:
    try:
        response = client.head(url, follow_redirects=True)
        if response.status_code >= 400 or response.status_code == 405:
            response = client.get(url, follow_redirects=True)
        return response.status_code, None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def crawl_site(start_url: str, config: CrawlConfig) -> dict[str, object]:
    visited_pages: set[str] = set()
    queued_pages: set[str] = set()
    checked_links: set[str] = set()
    queue = deque([start_url])
    queued_pages.add(start_url)
    broken_links: list[dict[str, object]] = []
    contact_signals = {
        "has_contact_page": False,
        "contact_page_url": None,
        "emails_found": [],
        "has_mailto": False,
        "has_tel": False,
    }
    robots = _load_robots(start_url) if config.respect_robots else None

    with httpx.Client(timeout=15.0, headers={"User-Agent": "seo-lead-audit-bot/0.1"}) as client:
        while queue and len(visited_pages) < config.max_pages:
            current = queue.popleft()
            if current in visited_pages:
                continue
            if robots and not robots.can_fetch("*", current):
                continue

            try:
                response = client.get(current, follow_redirects=True)
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                broken_links.append({"source_page": current, "url": current, "status": None, "error": str(exc)})
                visited_pages.add(current)
                time.sleep(config.delay_seconds)
                continue

            html = response.text
            links = extract_links(html)
            page_contact = find_contact_signals(html, str(response.url), links)
            if page_contact["has_contact_page"] and not contact_signals["has_contact_page"]:
                contact_signals["has_contact_page"] = True
                contact_signals["contact_page_url"] = page_contact["contact_page_url"]
            if page_contact["emails_found"]:
                contact_signals["emails_found"] = sorted(
                    set(contact_signals["emails_found"]) | set(page_contact["emails_found"])
                )
            contact_signals["has_mailto"] = bool(contact_signals["has_mailto"] or page_contact["has_mailto"])
            contact_signals["has_tel"] = bool(contact_signals["has_tel"] or page_contact["has_tel"])

            for href in links:
                target = normalize_link(str(response.url), href)
                if not target:
                    continue
                if target not in checked_links:
                    checked_links.add(target)
                    status_code, error = _check_link(client, target)
                    if (status_code is not None and status_code >= 400) or error:
                        broken_links.append(
                            {
                                "source_page": str(response.url),
                                "url": target,
                                "status": status_code,
                                "error": error,
                            }
                        )
                if is_internal_url(start_url, target) and target not in visited_pages and target not in queued_pages:
                    if robots and not robots.can_fetch("*", target):
                        continue
                    queue.append(target)
                    queued_pages.add(target)

            visited_pages.add(str(response.url))
            time.sleep(config.delay_seconds)

    return {
        "status": "ok",
        "start_url": start_url,
        "visited_pages": len(visited_pages),
        "max_pages": config.max_pages,
        "checked_links": len(checked_links),
        "broken_links_count": len(broken_links),
        "broken_links": broken_links[:100],
        "contact_signals": contact_signals,
    }
