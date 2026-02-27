# Website Fixer Lead Gen — Technical Implementation Design (Python + uv + Docker)

**Audience:** Codex/agentic coding system that will implement the MVP end-to-end.  
**Scope:** Cleveland-first local leads → automated audits → LLM summary + email draft → Notion board → human-approved email sending → suppression/opt-outs.

---

## 0) Assumptions (can be changed later)

- **Lead source:** Google Places API (no scraping).
- **Workflow UI:** Notion board is the primary workflow surface.
- **Artifacts:** stored locally in a Docker volume, optionally served via the API for clickable links.
- **Send flow:** Create **Gmail drafts** for human review + manual send (MVP).  
  (Alternative is “Approve → Send” internal page; not in MVP.)
- **Send volume:** 3–5/day enforced by code.
- **Crawl limit:** 10 pages max per site, rate-limited per domain.

If any assumption is wrong, adjust in Section 12 “Critical Questions”.

---

## 1) Goals and non-goals

### Goals
- Discover local businesses in Cleveland by category + radius.
- Extract a usable website URL.
- Run **basic checks**: HTTPS/cert, broken links, contact signals, Lighthouse snapshot.
- Generate a short, evidence-based summary + short email draft.
- Push lead + evidence links into a Notion board.
- Human-in-the-loop: system produces drafts; human decides what gets sent.
- Maintain **suppression list** for opt-outs and bounces.

### Non-goals (MVP)
- Automated follow-ups
- Reply parsing / automatic CRM enrichment
- Security/vulnerability scanning
- Deep SEO audits across entire site
- Scaling beyond modest concurrency

---

## 2) Tech stack

### Language & packaging
- Python **3.12+**
- `uv` for dependency management and running commands

### Libraries (recommended)
- API: `fastapi`, `uvicorn`
- Settings: `pydantic-settings`
- DB: `sqlalchemy` + `alembic` (or `sqlmodel`), Postgres driver `psycopg[binary]`
- Queue: `celery` + `redis`
- HTTP: `httpx`
- HTML parse: `selectolax` (fast) or `beautifulsoup4`
- Robots: built-in `urllib.robotparser`
- Screenshot: `playwright` (headless chromium)
- Notion: `notion-client`
- Google Places: direct `httpx` calls (simpler than heavy SDK)
- Phone/email parsing: `phonenumbers` (optional) + regex
- LLM: `openai` Python SDK

### Why Postgres (even if you want “simple”)
Notion is a workflow board, not reliable storage for:
- scheduling state
- suppression list
- audit artifacts metadata
- retries/error history

**Use Postgres for state** + Notion for visibility.

---

## 3) Containers (docker-compose)

Minimum containers:
- `api` — FastAPI endpoints + internal admin routes
- `worker` — Celery worker that runs discovery/audit/summarize/draft/sync
- `scheduler` — Celery beat (or a simple cron container) for periodic discovery
- `redis` — broker/backing store for celery
- `db` — Postgres
- `audit` — Node-based Lighthouse runner (recommended; Lighthouse is Node-first)

Optional:
- `playwright` can run inside `worker` (install browser deps in the worker image)

### Compose sketch
```yaml
services:
  api:
    build: ./services/api
    env_file: .env
    ports: ["8080:8080"]
    depends_on: [db, redis]
    volumes:
      - artifacts:/data/artifacts

  worker:
    build: ./services/worker
    env_file: .env
    depends_on: [db, redis, audit]
    volumes:
      - artifacts:/data/artifacts

  scheduler:
    build: ./services/worker
    env_file: .env
    command: ["uv", "run", "celery", "-A", "app.worker", "beat", "-l", "INFO"]
    depends_on: [db, redis]

  audit:
    build: ./services/audit
    env_file: .env
    ports: ["8081:8081"]

  redis:
    image: redis:7-alpine

  db:
    image: postgres:16-alpine
    env_file: .env
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
  artifacts:
```

---

## 4) Repo layout (monorepo)

```
leadgen/
  services/
    api/
      Dockerfile
      pyproject.toml
      app/
        main.py
        routes/
          health.py
          leads.py
          artifacts.py
          admin.py
        db.py
        models.py
        settings.py
    worker/
      Dockerfile
      pyproject.toml
      app/
        worker.py
        tasks/
          discover.py
          audit.py
          summarize.py
          notion_sync.py
          gmail_drafts.py
        audit/
          crawler.py
          tls_check.py
          lighthouse_client.py
          screenshots.py
          extract.py
        llm/
          prompts.py
          schemas.py
        db.py
        models.py
        settings.py
    audit/  (Node lighthouse microservice)
      Dockerfile
      package.json
      src/
        server.js
  migrations/ (alembic)
  docker-compose.yml
  .env.example
  README.md
```

---

## 5) Configuration / secrets

Use environment variables (12-factor). Store a `.env.example` committed; real `.env` ignored.

Required:
- `DATABASE_URL=postgresql+psycopg://...`
- `REDIS_URL=redis://redis:6379/0`
- `NOTION_TOKEN=...`
- `NOTION_DATABASE_ID=...`
- `OPENAI_API_KEY=...`
- `GOOGLE_PLACES_API_KEY=...`
- `SENDER_NAME=...`
- `SENDER_EMAIL=...`
- `PHYSICAL_ADDRESS=...`
- `OPT_OUT_INSTRUCTIONS=reply "unsubscribe"`
- `DAILY_SEND_CAP=5`
- `CRAWL_MAX_PAGES=10`
- `CRAWL_DELAY_SECONDS=1.0`
- `AUDIT_LIGHTHOUSE_URL=http://audit:8081/run`

Gmail drafts (if using Gmail API):
- `GMAIL_OAUTH_CLIENT_ID=...`
- `GMAIL_OAUTH_CLIENT_SECRET=...`
- `GMAIL_OAUTH_REFRESH_TOKEN=...`

---

## 6) Database schema (MVP)

### Tables
**leads**
- `id` UUID PK
- `name` text
- `category` text
- `source` text
- `place_id` text nullable
- `website_url` text
- `address` text nullable
- `phone` text nullable
- `email` text nullable
- `status` text (enum-like)
- `notion_page_id` text nullable
- `created_at`, `updated_at`

**audits**
- `id` UUID PK
- `lead_id` FK
- `started_at`, `finished_at`
- `final_url` text
- `https_ok` bool
- `redirect_chain` jsonb
- `cert_error` text nullable (expired/hostname/untrusted/other)
- `lighthouse_summary` jsonb
- `crawl_summary` jsonb
- `contact_signals` jsonb
- `artifact_index` jsonb (paths/filenames)

**issues**
- `id` UUID PK
- `audit_id` FK
- `kind` text (broken_link/cert/seo/contact/perf)
- `severity` int (1–5)
- `title` text
- `details` jsonb (proof: source_page, url, status, etc.)

**email_drafts**
- `id` UUID PK
- `lead_id` FK
- `audit_id` FK
- `subject` text
- `body_text` text
- `created_at`
- `approved_at` nullable
- `sent_at` nullable
- `gmail_draft_id` nullable
- `gmail_draft_url` nullable

**outreach_events**
- `id` UUID PK
- `lead_id` FK
- `type` text (drafted/approved/sent/bounced/replied/opt_out)
- `payload` jsonb
- `created_at`

**suppression**
- `id` UUID PK
- `email_or_domain` text unique
- `reason` text
- `created_at`

---

## 7) Notion database schema (board)

Notion DB: “Leads”

Properties (must match what code expects):
- `Name` (title)
- `Status` (select)
- `Category` (select)
- `Source` (select)
- `Website` (url)
- `Email` (email)
- `Phone` (rich text)
- `Address` (rich text)
- `Findings` (rich text)
- `Proof` (rich text / url) — links to artifacts served by API
- `Email Draft` (rich text)
- `Gmail Draft Link` (url)
- `Last Contacted` (date)
- `Opt-out` (checkbox)
- `Notes` (rich text)

Implementation note: store Notion `page_id` in `leads.notion_page_id` and update in place.

### Board views (manual setup instructions)

Create these views in the Notion `Leads` database after properties exist:

1) `Pipeline` (Board)
- Group by: `Status`
- Visible groups (recommended order): `Discovered`, `Audited`, `Draft Ready`, `Approved`, `Drafted`, `Sent`, `Replied`, `Suppressed`
- Card preview fields: `Category`, `Website`, `Email`, `Gmail Draft Link`, `Opt-out`
- Sort: `Status` (manual board order), then `Name` ascending

2) `Needs Review` (Table)
- Filter: `Status` is `Draft Ready` OR `Approved`
- Filter: `Opt-out` is unchecked
- Columns visible: `Name`, `Category`, `Findings`, `Proof`, `Email Draft`, `Gmail Draft Link`, `Status`
- Sort: `Last edited time` descending (or `Last Contacted` descending if you add automations)

3) `Suppressed` (Table)
- Filter: `Opt-out` is checked OR `Status` is `Suppressed`
- Columns visible: `Name`, `Email`, `Website`, `Status`, `Notes`

4) `Ready To Send` (Table, optional if using Gmail drafts)
- Filter: `Status` is `Approved`
- Filter: `Opt-out` is unchecked
- Columns visible: `Name`, `Email`, `Email Draft`, `Gmail Draft Link`, `Proof`

Operational notes:
- Keep `Status` select option names exactly aligned with app writes (case-sensitive enough to matter operationally).
- `Proof` can contain artifact links served from `/artifacts/*`; enable API Basic Auth if exposed beyond localhost.
- `Gmail Draft Link` may be empty when OAuth is not configured (manual copy/paste workflow remains valid MVP).

---

## 8) Task queue design (Celery)

### Task names (idempotent)
- `discover_leads(city, category, radius)`
- `audit_lead(lead_id)`
- `summarize_and_draft(lead_id, audit_id)`
- `sync_notion(lead_id, audit_id, draft_id)`
- `create_gmail_draft(draft_id)`  (optional step)
- `apply_suppression(lead_id)` (mark suppressed when opt-out flagged)

### Retry policy
- Discovery: retry a few times on HTTP errors.
- Audit: retry once on transient errors; store failures as events.
- LLM: retry on rate limit; otherwise fail and mark “needs manual”.

### Rate limiting
- Domain crawl: `CRAWL_DELAY_SECONDS` delay between fetches; max concurrency per domain = 1
- Sends: enforce `DAILY_SEND_CAP` in DB (count of sent today)

---

## 9) Lead discovery implementation

### Input
- `city="Cleveland, OH"`
- `category` keyword (e.g., “HVAC”, “dentist”)
- `radius_meters` (e.g., 15km)

### Steps
1) Call Places API “Text Search” or “Nearby Search” (based on your query style).
2) For each result:
   - store `place_id`, `name`, `formatted_address`, `phone` (if available)
3) Call Place Details for each `place_id` to obtain `website`
4) Normalize website URL (strip tracking params, force scheme)
5) Upsert into `leads` (unique by place_id or website domain)

### Dedup rules
- If multiple leads share same domain: keep one lead, attach aliases in notes.

---

## 10) Audit Worker implementation details

### 10.1 URL normalization
- Ensure scheme exists (`https://` default)
- Remove fragments
- Canonicalize trailing slash for homepage

### 10.2 HTTPS / redirect checks
- Perform `GET` with redirects enabled
- Record redirect chain
- Determine if http→https is present
- Record final URL and status code

### 10.3 TLS certificate check
Options:
- Simple: attempt HTTPS request with verification; classify exceptions
- More detailed: open `ssl` socket and parse cert dates/hostname

Store:
- `https_ok` boolean
- `cert_error` string category, if any

### 10.4 Crawl broken links (10 pages max)
Algorithm:
- BFS queue initialized with final homepage URL
- Fetch HTML (respect robots.txt; throttle)
- Extract `<a href>`; normalize; classify internal vs external
- For each extracted link:
  - HEAD or GET to check status (limit timeouts)
  - store broken links (>=400) with proof {source_page, url, status}
- Continue until:
  - visited_pages == max_pages
  - queue empty

Store:
- crawl summary counts
- top broken links list
- issues rows for each broken link (cap stored issues to avoid huge DB)

### 10.5 Contact signals
- Find “Contact” page by anchor text (case-insensitive) or `/contact` heuristic
- Extract emails: `mailto:` and regex
- Extract phone: `tel:` and optional `phonenumbers` parse
- Record booleans + found values

### 10.6 Lighthouse snapshot (via audit service)
- Call `POST /run` on the Node service with URL
- Store:
  - performance score
  - SEO score
  - key metrics (LCP, CLS, INP/TBT depending on report)
  - link to HTML report artifact (optional)

### 10.7 Screenshot
- Use Playwright to load page and screenshot above-the-fold
- Store screenshot path in artifacts volume
- Expose via API route for Notion links (basic auth recommended)

---

## 11) LLM summarization + email drafting

### Structured output schema (recommended)
Generate a JSON object:
- `lead_profile` (80–120 words)
- `quick_wins` (array of 3 items, each: `title`, `why_it_matters`, `how_to_fix`)
- `email_subject`
- `email_body_text` (plain text, short)
- `claims_used` (array of references to issue IDs / proof items)

### Prompt rules
- Only include findings that have proof fields (URLs, status codes, cert error, lighthouse score).
- Keep email under ~120–150 words.
- One CTA.
- Include opt-out line + physical address placeholders.

### Compliance footer template (always appended)
- Sender identity
- Physical address
- Opt-out instruction: “Reply ‘unsubscribe’”

**Do not** mention AI or automation.

---

## 12) Outreach (human approval)

### Gmail Draft flow (MVP)
- Task creates a Gmail draft using Gmail API.
- Store `gmail_draft_id` and optional link.
- Notion record updated with “Gmail Draft Link” or at least a note “Draft created; search subject”.

Fallback if Gmail API is too heavy:
- Store email text in Notion and manually paste into Gmail (still acceptable for MVP).

### Suppression / opt-out
- If lead replies “unsubscribe”:
  - manually check “Opt-out” in Notion OR call an admin endpoint
  - system writes suppression row and prevents future drafts/sends

---

## 13) API endpoints (FastAPI)

Public (or internal-only behind auth):
- `GET /healthz`
- `GET /leads?status=...`
- `GET /leads/{id}`
- `POST /admin/run-discovery` (manual trigger)
- `POST /admin/run-audit/{lead_id}`
- `GET /artifacts/{path}` (serve screenshot/report; protect with basic auth)
- `POST /admin/mark-optout/{lead_id}`

API is primarily for your internal use and Notion artifact links.

---

## 14) Observability

- Structured logs (json)
- Persist task failures in `outreach_events`
- Basic metrics:
  - audits/day
  - drafts/day
  - sends/day
  - failures/day

MVP: logs + DB events are enough.

---

## 15) Testing plan

Unit tests:
- URL normalization
- Link extraction and classification
- Robots.txt allow/deny logic
- Suppression enforcement
- Daily send cap logic

Integration tests:
- Run audit against a known test site with intentional 404 links
- Run Lighthouse service in docker and validate response schema

---

## 16) Milestones (Codex-friendly)

Status note (2026-02-27): checklist reflects current implementation. API route coverage now broad (admin/read/webhook/metrics), webhook provider auth/payload adapters are implemented and documented in `docs/website_fixer_leads_webhooks_integration_guide.md`. Remaining notable gap: full container E2E smoke on a running Docker/Podman engine.

### Milestone 1 — Skeleton + infra
- [x] Repo + uv projects for api/worker
- [x] docker-compose with api/worker/db/redis/audit
- [x] DB migrations + models

### Milestone 2 — Notion board integration
- [x] Create Notion DB schema doc + property mapping
- [x] Create/update lead pages
- [x] Board views manual setup instructions

### Milestone 3 — Lead discovery
- [x] Places API calls (search + details)
- [x] Upsert leads
- [x] Sync to Notion (Status=Discovered)

### Milestone 4 — Audit pipeline
- [x] HTTPS/redirect/cert checks
- [x] Crawl broken links (10 pages)
- [x] Contact signals extraction
- [x] Screenshot artifact + serving route
- [x] Lighthouse call + store summary

### Milestone 5 — LLM summary + email draft
- [x] Structured output generation
- [x] Proof-only rule enforced
- [x] Write email draft into Notion

### Milestone 6 — Human approval workflow
- [x] Create Gmail drafts OR store ready-to-send content
- [x] Add suppression list + opt-out flag
- [x] Enforce daily cap

---

## 17) Critical questions (must answer or we assume defaults)

1) **Which 2 categories** first in Cleveland? (e.g., “HVAC” + “dentist”)  
2) **Lead radius**: 5 mi / 10 mi / 15 mi / 25 mi? (default: 15 mi)  
3) **Email sending method**:
   - Gmail drafts via API (requires OAuth setup), or
   - “manual copy/paste” from Notion (simplest)  
4) **Artifact links**: do you want clickable proof links inside Notion?
   - If yes: API needs a public URL (or VPN) and basic auth.  
5) **Where to run this**: local server vs VPS? (affects artifact URLs, uptime)  
6) **LLM model choice** and cost tolerance (default: mid-tier model, low temp)  
7) **Robots.txt policy**: respect (default: yes) or ignore (not recommended)  
8) **Physical address** to include in footer (PO box ok)  
9) **Opt-out mechanism**:
   - reply-only (“unsubscribe”), or
   - reply + link to opt-out page (requires small web page)

If you answer 1–4, Codex can implement with clean defaults for the rest.
