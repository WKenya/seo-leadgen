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

