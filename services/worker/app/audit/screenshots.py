from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import re
from urllib.parse import urlparse

SAFE_SEGMENT = re.compile(r"[^a-z0-9.-]+")


def _slug_host(url: str) -> str:
    host = (urlparse(url).netloc or "unknown").lower()
    host = SAFE_SEGMENT.sub("-", host).strip("-.")
    return host or "unknown"


def build_screenshot_relpath(url: str, *, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    return f"screenshots/{_slug_host(url)}/{stamp}.png"


async def _capture_async(url: str, output_path: Path) -> dict[str, object]:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"playwright_unavailable: {exc}") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.screenshot(path=str(output_path), full_page=False)
            viewport = page.viewport_size or {}
        finally:
            await browser.close()

    return {
        "status": "ok",
        "url": url,
        "artifact_path": str(output_path),
        "width": viewport.get("width"),
        "height": viewport.get("height"),
    }


def capture_homepage_screenshot(url: str) -> dict[str, object]:
    from app.settings import get_settings

    settings = get_settings()
    relpath = build_screenshot_relpath(url)
    output_path = Path(settings.artifacts_root) / relpath
    result = asyncio.run(_capture_async(url, output_path))
    result["artifact_path"] = relpath
    return result
