# Website Fixer Lead Generation — System Design (MVP)

**Goal:** Automated discovery + audits + profiling + email drafting, with **human approval** before sending. Data and workflow live in **Notion**.

---

## 1) High-level architecture

### Services (minimal split)
1) **Lead Discovery**
- Finds local businesses and their website URLs (Cleveland-first).
- Stores leads into the database and/or Notion.

2) **Audit Worker**
- Runs automated checks (HTTPS/cert, broken links, contact signals, Lighthouse).
- Produces structured audit output + evidence artifacts.

3) **LLM Summarizer + Email Drafter**
- Converts audit output into:
  - short lead profile summary
  - “top 3 quick wins”
  - short email draft

4) **Notion Sync**
- Creates/updates Notion records to power the Kanban board.

5) **Outreach (Human-in-the-loop)**
- Creates a “Ready to send” draft (e.g., Gmail draft link, or internal send queue).
- Sends only after human approval.
- Records send events + maintains suppression list.

---

## 2) Pipeline / workflow

### Status states (Notion “Status” select)
- Discovered
- Audited
- Draft Ready
- Approved to Send
- Sent
- Replied
- Won
- Lost
- Suppressed

### Job flow
1) `discover_leads(city="Cleveland", category, radius)`
2) `audit_lead(lead_id)`
3) `summarize_lead(lead_id, audit_id)`
4) `draft_email(lead_id, audit_id)`
5) `sync_notion(lead_id)`
6) `create_send_draft(lead_id)`  (Gmail draft or internal pending send)
7) Human approves → `send_email(lead_id)`
8) `record_outreach_event(lead_id, sent/bounced/replied/opt_out)`

---

## 3) Audit checks (MVP)

### Crawl scope
- Homepage + internal crawl up to **10 pages** (configurable).
- Respect robots.txt (recommended) and rate-limit requests.

### Checks
1) **HTTPS + redirect sanity**
- http → https redirect exists and resolves
- no redirect loops

2) **Certificate validity**
- expired / hostname mismatch / untrusted CA

3) **Broken links**
- record 404/5xx internal links
- record broken outbound links
- store proof: source page + target URL + status code

4) **Contactability**
- contact page present?
- phone/email present?
- “mailto:” links present?

5) **Basic SEO hygiene**
- title tag exists
- meta description exists
- robots noindex present?
- canonical present? (optional)

6) **Performance snapshot**
- Lighthouse run (mobile profile)
- store key metrics (performance score, LCP/CLS/INP or closest available)
- attach HTML report if desired

**Rule:** Do not claim anything in outreach that you can’t back up with stored evidence.

---

## 4) Data model (minimal)

### Tables / collections (if using Postgres)
**leads**
- id (uuid)
- name
- category
- source
- place_id (optional)
- website_url
- address
- phone
- email (if found)
- status
- notion_page_id
- created_at, updated_at

**audits**
- id (uuid)
- lead_id (fk)
- started_at, finished_at
- https_status
- cert_error
- lighthouse_json (or structured subset)
- crawl_summary_json
- contact_signals_json
- raw_artifacts_path (where screenshots/reports live)

**issues**
- id
- audit_id
- kind (broken_link / cert / seo / contact / perf)
- severity
- title
- details_json (includes proof: URL, status, source_page, etc.)

**email_drafts**
- id
- lead_id
- audit_id
- subject
- body_text
- created_at
- approved_at (nullable)
- sent_at (nullable)
- gmail_draft_url (optional)

**outreach_events**
- id
- lead_id
- type (drafted/approved/sent/bounced/replied/opt_out)
- payload_json
- created_at

**suppression**
- id
- email_or_domain
- reason (opt_out/bounce/complaint/manual)
- created_at

### If you want “no DB” MVP
You can store most of this inside Notion, but you still need:
- a local suppression list (file/kv/db)
- a place to store artifacts (local disk or object storage)

---

## 5) Notion schema (board-friendly)

Database: **Leads**

Properties:
- Name (Title)
- Status (Select)
- Category (Select)
- Source (Select)
- Website (URL)
- Email (Email)
- Phone (Text)
- Address (Text)
- Findings (Rich text)
- Proof (Files / links)
- Email Draft (Rich text)
- Draft Link (URL)
- Last Contacted (Date)
- Opt-out (Checkbox)
- Notes (Rich text)

Views:
- Board view grouped by Status
- Table view with filters (e.g., only “Draft Ready”)

---

## 6) Queue + scheduling

Use a job queue so audits don’t block everything:
- Redis + BullMQ (TypeScript) **or** Hangfire (.NET)
- Rate-limit:
  - discovery jobs per day
  - audit concurrency
  - per-domain crawl throttling

Suggested schedules:
- Discovery: daily at low-traffic time
- Audits: continuous, but throttled
- Draft generation: runs after audits

---

## 7) Human approval design

### Option A (simplest): Gmail Drafts
- System creates a Gmail draft
- Notion card includes the draft link
- You review, edit, and send manually

### Option B: Internal “Approve → Send”
- Tiny internal page that shows:
  - audit evidence
  - email draft
  - approve/send buttons
- Still human-controlled, but more integrated

MVP recommendation: **Option A**.

---

## 8) Guardrails (must-have)

- Daily send cap: **3–5**
- No automated follow-ups for the first 2 weeks
- Suppression list checked before drafting/sending
- Evidence required for every claim
- Crawl throttling + timeouts
- Store “last audited” time to avoid re-auditing too often

---

## 9) Open items (decisions)

1) Pick two categories to start in Cleveland  
2) Choose approval method: Gmail drafts (recommended) vs internal approval page  
3) Where artifacts live: local disk vs object storage  
4) Sender identity + compliance footer data (physical address, opt-out handling)

