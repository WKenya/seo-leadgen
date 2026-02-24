from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlparse

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def extract_emails(text: str) -> list[str]:
    return sorted(set(EMAIL_PATTERN.findall(text)))


def normalize_link(base_url: str, href: str) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    return urljoin(base_url, href)


def is_internal_url(site_url: str, candidate_url: str) -> bool:
    return urlparse(site_url).netloc == urlparse(candidate_url).netloc


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def extract_links(html_text: str) -> list[str]:
    parser = _LinkParser()
    parser.feed(html_text)
    return parser.hrefs


class _SeoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self._title_parts: list[str] = []
        self.meta_description: str | None = None
        self.canonical_href: str | None = None
        self.robots_content: str | None = None

    @property
    def title(self) -> str | None:
        title = "".join(self._title_parts).strip()
        return title or None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
            return
        if tag == "meta":
            name = attrs_dict.get("name", "").lower()
            content = attrs_dict.get("content", "")
            if name == "description" and content and self.meta_description is None:
                self.meta_description = content.strip() or None
            if name == "robots" and content and self.robots_content is None:
                self.robots_content = content.strip() or None
            return
        if tag == "link":
            rel = attrs_dict.get("rel", "").lower()
            href = attrs_dict.get("href", "").strip()
            if "canonical" in rel and href and self.canonical_href is None:
                self.canonical_href = href

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)


def find_contact_signals(html_text: str, base_url: str, links: list[str]) -> dict[str, object]:
    normalized_links = [normalize_link(base_url, href) for href in links]
    normalized_links = [u for u in normalized_links if u]
    emails = extract_emails(html_text)
    has_mailto = "mailto:" in html_text.lower()
    has_tel = "tel:" in html_text.lower()
    contact_page = None
    for href in links:
        text = href.lower()
        if "contact" in text:
            maybe = normalize_link(base_url, href)
            if maybe:
                contact_page = maybe
                break
    if contact_page is None:
        for u in normalized_links:
            if "/contact" in u.lower():
                contact_page = u
                break
    return {
        "has_contact_page": bool(contact_page),
        "contact_page_url": contact_page,
        "emails_found": emails,
        "has_mailto": has_mailto,
        "has_tel": has_tel,
    }


def extract_basic_seo_signals(html_text: str, base_url: str) -> dict[str, object]:
    parser = _SeoParser()
    parser.feed(html_text)
    canonical = normalize_link(base_url, parser.canonical_href) if parser.canonical_href else None
    robots_content = parser.robots_content or ""
    robots_tokens = [token.strip().lower() for token in robots_content.split(",") if token.strip()]
    return {
        "title_present": bool(parser.title),
        "title": parser.title,
        "meta_description_present": bool(parser.meta_description),
        "meta_description": parser.meta_description,
        "canonical_present": bool(canonical),
        "canonical_url": canonical,
        "robots_noindex": "noindex" in robots_tokens,
        "robots_content": parser.robots_content,
    }


def choose_preferred_email(emails: list[str]) -> str | None:
    if not emails:
        return None
    lower = [e.lower() for e in emails]
    non_role = [e for e in lower if not e.startswith(("admin@", "info@", "support@", "hello@", "contact@"))]
    if non_role:
        return sorted(non_role)[0]
    return sorted(lower)[0]
