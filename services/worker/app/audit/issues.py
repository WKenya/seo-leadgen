from __future__ import annotations

from collections import defaultdict
from typing import Any


def aggregate_broken_links(
    broken_links: list[dict[str, Any]],
    *,
    max_groups: int = 25,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int | None, str | None], dict[str, Any]] = {}
    source_pages_by_key: dict[tuple[str, int | None, str | None], set[str]] = defaultdict(set)

    for row in broken_links:
        url = str(row.get("url") or "")
        status = row.get("status")
        error = row.get("error")
        key = (url, status if isinstance(status, int) else None, str(error) if error else None)
        if key not in grouped:
            grouped[key] = {
                "url": url,
                "status": status if isinstance(status, int) else None,
                "error": str(error) if error else None,
                "occurrences": 0,
                "source_pages_sample": [],
            }
        grouped[key]["occurrences"] += 1
        source_page = row.get("source_page")
        if isinstance(source_page, str) and source_page:
            source_pages_by_key[key].add(source_page)

    rows = []
    for key, data in grouped.items():
        sample = sorted(source_pages_by_key[key])[:5]
        item = dict(data)
        item["source_pages_sample"] = sample
        rows.append(item)

    rows.sort(
        key=lambda r: (
            -int(r.get("occurrences") or 0),
            0 if (r.get("status") or 0) >= 500 else 1,
            str(r.get("url") or ""),
        )
    )
    return rows[:max_groups]

