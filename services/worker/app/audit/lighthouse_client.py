import httpx


def run_lighthouse(audit_service_url: str, url: str) -> dict[str, object]:
    # Placeholder; real impl will validate response schema and retries.
    with httpx.Client(timeout=30.0) as client:
        response = client.post(audit_service_url, json={"url": url})
        response.raise_for_status()
        return response.json()

