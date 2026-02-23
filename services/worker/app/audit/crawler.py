from dataclasses import dataclass


@dataclass(slots=True)
class CrawlConfig:
    max_pages: int = 10
    delay_seconds: float = 1.0
    respect_robots: bool = True


def crawl_site(start_url: str, config: CrawlConfig) -> dict[str, object]:
    return {
        "status": "stub",
        "start_url": start_url,
        "visited_pages": 0,
        "max_pages": config.max_pages,
    }

