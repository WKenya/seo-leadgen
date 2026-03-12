from __future__ import annotations

from urllib.parse import urlparse, urlunparse

import httpx


def _is_default_port_for_scheme(scheme: str, port: int) -> bool:
    return (scheme == "https" and port == 443) or (scheme == "http" and port == 80)


def _with_scheme(url: str, scheme: str) -> str:
    normalized_url = (url or "").strip()
    parsed = urlparse(normalized_url if "://" in normalized_url else f"https://{normalized_url}")
    source_scheme = parsed.scheme.lower() or "https"
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return urlunparse((scheme, "", (parsed.path or "/").strip() or "/", "", parsed.query, ""))

    host = f"[{hostname}]" if ":" in hostname else hostname
    port_value: int | None
    try:
        port_value = parsed.port
    except ValueError:
        port_value = None

    if port_value is None:
        netloc = host
    elif _is_default_port_for_scheme(source_scheme, port_value) or _is_default_port_for_scheme(scheme, port_value):
        netloc = host
    else:
        netloc = f"{host}:{port_value}"

    return urlunparse((scheme, netloc, (parsed.path or "/").strip() or "/", "", parsed.query, ""))


def _classify_cert_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "certificate verify failed" in text or "ssl" in text:
        if "hostname" in text:
            return "hostname_mismatch"
        if "expired" in text:
            return "expired"
        return "untrusted_or_invalid"
    return "other"


def _fetch_chain(url: str) -> tuple[list[dict[str, object]], str | None, str | None]:
    chain: list[dict[str, object]] = []
    try:
        with httpx.Client(follow_redirects=True, timeout=15.0) as client:
            response = client.get(url)
            for step in [*response.history, response]:
                chain.append({"url": str(step.url), "status_code": step.status_code})
            return chain, str(response.url), None
    except Exception as exc:  # noqa: BLE001
        return chain, None, _classify_cert_error(exc)


def check_tls(url: str) -> dict[str, object]:
    http_url = _with_scheme(url, "http")
    https_url = _with_scheme(url, "https")
    http_chain, http_final, http_err = _fetch_chain(http_url)
    https_chain, https_final, https_err = _fetch_chain(https_url)

    final_url = https_final or http_final or https_url
    redirect_chain = https_chain if https_chain else http_chain
    http_to_https = bool(http_final and http_final.startswith("https://"))
    https_ok = https_err is None and bool(https_final and https_final.startswith("https://"))

    return {
        "url": url,
        "final_url": final_url,
        "https_ok": https_ok,
        "http_to_https": http_to_https,
        "redirect_chain": redirect_chain,
        "cert_error": https_err or http_err,
    }
