#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass


@dataclass(slots=True)
class SeedFixture:
    lead_id: str
    audit_id: str
    issue_id: str
    draft_id: str
    event_id: str
    suppression_id: str
    lead_email: str
    marker: str


def _run(cmd: list[str]) -> None:
    print(f"+ {shlex.join(cmd)}")
    subprocess.run(cmd, check=True)


def _detect_compose_cmd() -> list[str]:
    raw = os.environ.get("SEO_LEAD_COMPOSE_CMD", "").strip()
    if raw:
        return shlex.split(raw)
    candidates = (["docker", "compose"], ["podman", "compose"], ["docker-compose"])
    for candidate in candidates:
        try:
            subprocess.run(
                [*candidate, "version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return list(candidate)
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    raise RuntimeError("no compose runtime found (docker/podman/docker-compose)")


def _psql(compose_cmd: list[str], statement: str) -> None:
    _run(
        [
            *compose_cmd,
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "postgres",
            "-d",
            "seo_lead",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            statement,
        ]
    )


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _ensure_schema_compatibility(compose_cmd: list[str]) -> None:
    # Keeps smoke harness resilient when container images lag behind latest migrations.
    _psql(compose_cmd, "ALTER TABLE outreach_events ADD COLUMN IF NOT EXISTS external_id VARCHAR(255);")
    _psql(
        compose_cmd,
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_outreach_events_external_id ON outreach_events (external_id);",
    )


def _http_json(base_url: str, path: str, params: dict[str, str] | None = None) -> dict[str, object]:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    last_error: Exception | None = None
    for _attempt in range(3):
        request = urllib.request.Request(url=url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"http error from {url}: {exc.code} {body}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"http request failed for {url}: {last_error}")


def _http_post_json(base_url: str, path: str, payload: dict[str, object]) -> dict[str, object]:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    body = json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None
    for _attempt in range(3):
        request = urllib.request.Request(
            url=url,
            data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"http error from {url}: {exc.code} {body_text}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"http request failed for {url}: {last_error}")


def _wait_for_service(base_url: str, *, service_name: str, timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            health = _http_json(base_url, "/healthz")
            if bool(health.get("ok")):
                return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(1.0)
    raise RuntimeError(f"{service_name} did not become healthy within {timeout_seconds}s: {last_error}")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _seed_fixture(compose_cmd: list[str]) -> SeedFixture:
    marker = f"e2e-{int(time.time())}"
    lead_name = f"E2E Smoke Lead {marker}"
    lead_id = str(uuid.uuid4())
    audit_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    draft_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    suppression_id = str(uuid.uuid4())
    lead_email = f"{marker}@example.com"

    payload = json.dumps(
        {
            "provider": "mailgun",
            "provider_event_id": f"{marker}-provider-event",
            "provider_event_name": "opened",
            "provider_event_at": "2026-02-01T00:00:00Z",
        }
    )
    crawl_summary = json.dumps({"visited_pages": 1, "checked_links": 1, "broken_links_count": 0})
    contact_signals = json.dumps({"has_contact_page": True, "emails_found": [lead_email]})
    issue_details = json.dumps({"url": "https://example.com/missing", "status": 404, "occurrences": 1})

    fixture = SeedFixture(
        lead_id=lead_id,
        audit_id=audit_id,
        issue_id=issue_id,
        draft_id=draft_id,
        event_id=event_id,
        suppression_id=suppression_id,
        lead_email=lead_email,
        marker=marker,
    )

    _psql(
        compose_cmd,
        " ".join(
            [
                "INSERT INTO leads (id, name, category, source, website_url, email, status)",
                "VALUES",
                f"({_sql_quote(fixture.lead_id)}::uuid, {_sql_quote(lead_name)}, {_sql_quote('HVAC')},",
                f"{_sql_quote('e2e_smoke')}, {_sql_quote('https://example.com')}, {_sql_quote(fixture.lead_email)}, {_sql_quote('Audited')});",
            ]
        ),
    )
    _psql(
        compose_cmd,
        " ".join(
            [
                "INSERT INTO audits (id, lead_id, started_at, finished_at, final_url, https_ok, redirect_chain, crawl_summary, contact_signals)",
                "VALUES",
                f"({_sql_quote(fixture.audit_id)}::uuid, {_sql_quote(fixture.lead_id)}::uuid, now(), now(), {_sql_quote('https://example.com')}, true,",
                f"{_sql_quote('[]')}::jsonb, {_sql_quote(crawl_summary)}::jsonb, {_sql_quote(contact_signals)}::jsonb);",
            ]
        ),
    )
    _psql(
        compose_cmd,
        " ".join(
            [
                "INSERT INTO issues (id, audit_id, kind, severity, title, details)",
                "VALUES",
                f"({_sql_quote(fixture.issue_id)}::uuid, {_sql_quote(fixture.audit_id)}::uuid, {_sql_quote('broken_link')}, 4,",
                f"{_sql_quote('Broken link (1x): https://example.com/missing')}, {_sql_quote(issue_details)}::jsonb);",
            ]
        ),
    )
    _psql(
        compose_cmd,
        " ".join(
            [
                "INSERT INTO email_drafts (id, lead_id, audit_id, subject, body_text)",
                "VALUES",
                f"({_sql_quote(fixture.draft_id)}::uuid, {_sql_quote(fixture.lead_id)}::uuid, {_sql_quote(fixture.audit_id)}::uuid,",
                f"{_sql_quote('Quick website fix idea')}, {_sql_quote('Two high-impact fixes found in your homepage audit.')} );",
            ]
        ),
    )
    _psql(
        compose_cmd,
        " ".join(
            [
                "INSERT INTO outreach_events (id, lead_id, type, payload)",
                "VALUES",
                f"({_sql_quote(fixture.event_id)}::uuid, {_sql_quote(fixture.lead_id)}::uuid, {_sql_quote('opened')},",
                f"{_sql_quote(payload)}::jsonb);",
            ]
        ),
    )
    _psql(
        compose_cmd,
        " ".join(
            [
                "INSERT INTO suppression (id, email_or_domain, reason)",
                "VALUES",
                f"({_sql_quote(fixture.suppression_id)}::uuid, {_sql_quote(fixture.lead_email)}, {_sql_quote('opt_out')});",
            ]
        ),
    )

    return fixture


def _cleanup_fixture(compose_cmd: list[str], fixture: SeedFixture | None) -> None:
    if fixture is None:
        return
    statements = [
        f"DELETE FROM issues WHERE id = {_sql_quote(fixture.issue_id)}::uuid;",
        f"DELETE FROM email_drafts WHERE id = {_sql_quote(fixture.draft_id)}::uuid;",
        f"DELETE FROM outreach_events WHERE id = {_sql_quote(fixture.event_id)}::uuid;",
        f"DELETE FROM audits WHERE id = {_sql_quote(fixture.audit_id)}::uuid;",
        f"DELETE FROM suppression WHERE id = {_sql_quote(fixture.suppression_id)}::uuid;",
        f"DELETE FROM leads WHERE id = {_sql_quote(fixture.lead_id)}::uuid;",
    ]
    for statement in statements:
        try:
            _psql(compose_cmd, statement)
        except Exception as exc:  # noqa: BLE001
            print(f"cleanup warning: {exc}", file=sys.stderr)


def _run_checks(base_url: str, fixture: SeedFixture) -> None:
    health = _http_json(base_url, "/healthz")
    _require(bool(health.get("ok")), "healthz ok flag != true")

    ready = _http_json(base_url, "/readyz")
    _require(bool(ready.get("ok")), "readyz ok flag != true")

    leads = _http_json(base_url, "/leads", {"q": fixture.marker, "sort": "asc", "limit": "10"})
    _require(leads.get("sort") == "asc", "/leads sort response mismatch")
    _require(any(item.get("id") == fixture.lead_id for item in leads.get("items", [])), "seed lead not found in /leads")

    lead = _http_json(base_url, f"/leads/{fixture.lead_id}")
    _require(lead.get("id") == fixture.lead_id, "lead detail id mismatch")

    audits = _http_json(base_url, f"/leads/{fixture.lead_id}/audits", {"sort": "asc", "limit": "10"})
    _require(audits.get("sort") == "asc", "/leads/{id}/audits sort response mismatch")
    _require(
        any(item.get("id") == fixture.audit_id for item in audits.get("items", [])),
        "seed audit not found in /leads/{id}/audits",
    )

    audit = _http_json(base_url, f"/audits/{fixture.audit_id}")
    _require(audit.get("id") == fixture.audit_id, "audit detail id mismatch")

    issues = _http_json(base_url, f"/audits/{fixture.audit_id}/issues")
    _require(any(item.get("id") == fixture.issue_id for item in issues.get("items", [])), "seed issue not found")

    drafts = _http_json(base_url, "/drafts", {"lead_id": fixture.lead_id, "sort": "asc", "limit": "10"})
    _require(drafts.get("sort") == "asc", "/drafts sort response mismatch")
    _require(any(item.get("id") == fixture.draft_id for item in drafts.get("items", [])), "seed draft not found in /drafts")

    lead_drafts = _http_json(base_url, f"/leads/{fixture.lead_id}/drafts", {"sort": "asc", "limit": "10"})
    _require(
        any(item.get("id") == fixture.draft_id for item in lead_drafts.get("items", [])),
        "seed draft not found in /leads/{id}/drafts",
    )

    events = _http_json(base_url, "/events", {"provider": "mailgun", "sort": "asc", "limit": "10"})
    _require(events.get("sort") == "asc", "/events sort response mismatch")
    _require(any(item.get("id") == fixture.event_id for item in events.get("items", [])), "seed event not found in /events")

    lead_events = _http_json(
        base_url,
        f"/leads/{fixture.lead_id}/events",
        {"provider": "mailgun", "sort": "asc", "limit": "10"},
    )
    _require(
        any(item.get("id") == fixture.event_id for item in lead_events.get("items", [])),
        "seed event not found in /leads/{id}/events",
    )

    suppression = _http_json(base_url, "/suppression", {"q": fixture.marker, "sort": "asc", "limit": "10"})
    _require(
        any(item.get("id") == fixture.suppression_id for item in suppression.get("items", [])),
        "seed suppression row not found",
    )

    pipeline = _http_json(base_url, f"/leads/{fixture.lead_id}/pipeline")
    _require((pipeline.get("latest_audit") or {}).get("id") == fixture.audit_id, "pipeline latest_audit mismatch")
    _require((pipeline.get("latest_draft") or {}).get("id") == fixture.draft_id, "pipeline latest_draft mismatch")

    metrics = _http_json(base_url, "/metrics/summary", {"provider": "mailgun", "latest_limit": "5"})
    provider_count = metrics.get("webhook_events_today_for_provider")
    _require(isinstance(provider_count, int) and provider_count >= 1, "metrics provider count missing")


def _run_audit_checks(audit_base_url: str) -> None:
    health = _http_json(audit_base_url, "/healthz")
    _require(bool(health.get("ok")), "audit /healthz ok flag != true")

    run_result = _http_post_json(audit_base_url, "/run", {"url": "http://localhost:8081/healthz"})
    _require(bool(run_result.get("ok")), "audit /run ok flag != true")
    summary = run_result.get("summary")
    _require(isinstance(summary, dict), "audit /run summary missing")
    for key in ("performance_score", "seo_score", "lcp_ms", "cls", "inp_ms"):
        _require(key in summary, f"audit /run summary missing key: {key}")


def main() -> int:
    compose_cmd = _detect_compose_cmd()
    api_base_url = os.environ.get("SEO_LEAD_API_BASE_URL", "http://localhost:8080")
    audit_base_url = os.environ.get("SEO_LEAD_AUDIT_BASE_URL", "http://localhost:8081")
    build_images = os.environ.get("SEO_LEAD_SMOKE_BUILD", "").strip().lower() in {"1", "true", "yes"}
    fixture: SeedFixture | None = None
    try:
        up_cmd = [*compose_cmd, "up", "--build", "-d"] if build_images else [*compose_cmd, "up", "-d"]
        _run(up_cmd)
        _run(
            [
                *compose_cmd,
                "exec",
                "-T",
                "worker",
                "uv",
                "run",
                "alembic",
                "-c",
                "/app/alembic.ini",
                "upgrade",
                "head",
            ]
        )
        _ensure_schema_compatibility(compose_cmd)
        _wait_for_service(api_base_url, service_name="api")
        _wait_for_service(audit_base_url, service_name="audit")
        _run_audit_checks(audit_base_url)
        fixture = _seed_fixture(compose_cmd)
        _run_checks(api_base_url, fixture)
        print("container e2e smoke: ok")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"container e2e smoke: failed: {exc}", file=sys.stderr)
        return 1
    finally:
        _cleanup_fixture(compose_cmd, fixture)


if __name__ == "__main__":
    raise SystemExit(main())
