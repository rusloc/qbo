# QBO P&L — AI Coding Instructions

> This file is for AI coding assistants working on the QBO P&L codebase.
> It contains pointers, user communication rules, logging routine, critical rules, and conventions (product spec lives in `.docs/`).

## Project identity

- **Project name**: QBO P&L
- **One-line purpose**: Productized, reusable Profit & Loss analytics for SME clients — QuickBooks Online (QBO) ledger → owned Python ETL → Supabase Postgres warehouse → Power BI template **and** a React online report.
- **Canonical domain / workspace**: Supabase project **`vosk.dev`** hosts the warehouse (USER 2026-09-25; project ref not recorded here — it lives in env / local config). The project is shared with the USER's other backends; QBO lives in its own schema (ADR-0008). Power BI / Fabric workspace: _not assigned yet_.
- **Public surface/URL**: _not assigned yet_ — URL of the React online report.
- **Repository**: GitHub `rusloc/qbo` — remote `origin` = `git@github.com:rusloc/qbo.git` (SSH)
- **Runtime hook**: env vars (`DB_URL`, `SUPABASE_URL`, `REALM_ID`, `ENV`) and the Power BI parameters `Server`, `Database`, `FY_START` are the canonical source of truth at runtime; do NOT hard-code a project ref, host, realmId or workspace in code. Values written above are for docs/copy only.

```
QBO API v3 (OAuth 2.0, one realm per client)
   │  query / cdc  (reports API = validation only)
   ▼
etl/  qbo_sync  (Python 3.12)  ──►  Supabase Postgres
                                    raw_entity → stg_* → dim_* / fact_* → serve views vw_*
                                                                         ├──►  Power BI model (Import)  → PNL/ (PBIP)
                                                                         └──►  React online report      → web/
```

---

## Quick navigation

| What | Where |
|------|-------|
| **Product spec** (scope, QBO API facts, schema, transform rules, phases, DAX, DoD, guardrails) — canonical | `.docs/qbo-pnl-project-spec.md` |
| Tool setup guide (HTML) | `.docs/setup-guide.html` |
| Application Design documents (ADD) | `.docs/ADD/` |
| Architecture Decision Records (ADRs) | `.docs/ADR/` |
| Feature specs | `.docs/ADD/features/` |
| Tech stack + rationale (incl. open choices) | `.docs/ADD/tech-stack.md` |
| Anti-patterns catalogue (codified bug-class memory) | `.docs/ADD/anti-patterns.md` |
| Power BI model docs (star schema, measure dictionary, refresh strategy) | `.docs/model/` |
| Features plan, log of implementation, user idea stash | `.log/features_and_decisions.md` |
| Raw ideas / parking lot | `.docs/ADD/ideas/ideas.md` |
| Agent kit runbook (install / verify / pitfalls) | `pbi-fabric-agent-kit/SETUP.md`, `pbi-fabric-agent-kit/MANIFEST.md` |

**Repository layout**
```
.docs/                  → spec, ADR/, ADD/, model/, setup-guide.html
.log/                   → coms/, daily/, plan/, weekly/, features_and_decisions.md
etl/  fixtures/  demo_data/   → Python ETL lane
supabase/               → Supabase CLI project (created by `supabase init`)
dbt/                    → dbt project `qbo_pnl` (transforms; ADR-0002)
PNL/                    → PBIP report project (created by Desktop)
web/                    → React report (created by the scaffold tool)
.claude/skills/         → project skills (agent kit)      .claude/common/ → shared files of the Microsoft skills
.claude/settings.json   → permission allow / deny lists (agent kit)
.mcp.json               → project MCP servers (powerbi-modeling)
_scripts/validate.py    → PBIP / JSON / encoding validator (agent kit)
scripts/                → setup + sync scripts (sync-pbi-fabric-skills.ps1)
_mcp/pg-sqldev/         → optional read-only Postgres catalog MCP (source only, not registered)
pbi-fabric-agent-kit/   → unpacked kit source (gitignored; not live config)
```
The kit's `context/` folder concept maps to this project as: business truth = spec + `.docs/model/`; database truth = `supabase/migrations/`. Don't create `context/`.

**Spec ↔ project deltas (USER decisions 2026-09-25, not yet folded into the spec):**
1. Warehouse = **Supabase Postgres only**. Spec §0 says "PostgreSQL or Azure SQL (parameterize; support both)" — the Azure SQL path is dropped (ADR-0001).
2. A **React online report** (third-party plotting library) is a second consumer of the serve layer. Spec §0 lists only the Power BI template — a spec amendment is pending.

Where this file / an accepted ADR and the spec disagree, this file and the ADR win. Flag every other spec conflict you find (spec §9.7) — don't resolve it silently.

---

## Work lanes

Single-agent project for now: the main agent does the work and routes to skills and tools by lane. If sub-agents are introduced later, each lane below becomes one agent (ADR first).

| Lane | Owns (paths) | Skills | Tools / MCP |
|------|--------------|--------|-------------|
| **ETL** (extract + load) | `etl/`, `fixtures/`, `demo_data/` | `python-cli-dev` | Python 3.12, pytest, QBO **sandbox** |
| **Warehouse** (Supabase SQL + dbt) | `supabase/` (migrations: DDL / init code, validation SQL), `dbt/` (transforms) | `db-schema-architect`, `pg-sql-dev`, `dax-sql-formatter` | Supabase MCP (`supabase`), dbt; `pg-sqldev` MCP once registered |
| **PBI model & report** | `PNL/`, `.docs/model/` | `pbip-editor`, `semantic-model-authoring`, `powerbi-report-cli`, `dax-sql-formatter` | Power BI Desktop, `powerbi-modeling` MCP, `powerbi-report-author`, `powerbi-desktop`, `_scripts/validate.py` |
| **PBI Service** (publish, workspace) | workspace items | `powerbi-report-cli` (management mode), `search-consumption-cli` | `fab`, `az` |
| **Web report** | `web/` | `front-end-web-dev-guru`, `dataviz`, `nextjs-react-code-reviewer`, `qa-testing-engineer` | Node, supabase-js |

- Cross-cutting concerns (security, performance, reconciliation) live as checklists inside the lane — not as new lanes.
- A metric that exists in both PBI and web is owned by the **Warehouse** lane (serve view column) and documented in `.docs/model/`; the two consumers only present it.

---

## ⛔ Critical rules — allowed / prohibited actions

These rules are load-bearing. They override convenience, speed, and any implicit inference from context. When a rule conflicts with a user request, surface the conflict — don't silently pick a side.

### 🛑 Rule #1 — PBIP safety: no edits without consent

> Scope: everything under `PNL/` (TMDL, PBIR, `.pbip`, `.pbi/`) and every model write through the `powerbi-modeling` MCP. Inside this scope Rule #1 outranks every other instruction in this file and in every skill.

- **No edit without a clear, explicit command.** Consent is per-task and does not carry over: "yes, do it" on one file is not permission for the next one, and a question — "why is this broken?", "what does this measure do?", "can you check X?" — is a request to *look*, never to *change*. If the instruction could be read as either, it is not consent. Ask.
- **Default action is to suggest, not apply.** Show the proposed diff and stop. Reading, searching, diffing, and running `validate.py` are always free. Anything that writes to disk waits for a go-ahead.
- **Copy before editing.** Once an edit is approved, snapshot every file it touches *before* the first write, to `PNL/__backup__/` mirroring the file's path under `PNL/`, suffixed `.<yyyy-MM-dd-HHmm>.bak`:
  `PNL/__backup__/<Name>.SemanticModel/definition/tables/<table>.tmdl.2026-10-01-1430.bak`
- **Match the target's bytes.** A rewrite must reproduce the existing encoding, BOM state and line endings exactly. Power BI Desktop on Windows writes **TMDL and PBIR as UTF-8 *without* BOM, CRLF** — measure the actual bytes before assuming, and never trust a checker that normalises them. Desktop refuses to open a project when a single file deviates.
- **Why:** in the project this kit comes from, an in-place rewrite of one `.tmdl` file prepended a 3-byte UTF-8 BOM. The logic was correct, no pre-edit copy existed, `validate.py` reported green (it strips the BOM before checking) — and the whole report stopped opening.

### Always allowed (no permission needed)
- Reading any file in the repo, docs, logs, and ADRs
- Appending to `.log/coms` during a session; refreshing daily / plan content while the day stays OPEN
- Proposing plans, flagging ADR candidates, surfacing risks and simpler alternatives
- Routing single-lane work to the owning lane's skills
- Compiling ready-to-paste command blocks (git, deploy, CLI) for the user to run
- Running local, read-only checks: tests against fixtures, linters, `--dry-run` modes

### Prohibited (never do, even if it seems helpful)
- **Never execute git commands or touch the working tree state** — output git commands as a single fenced bash block, ready to copy-paste; nothing more
- **Never reference Anthropic, Claude or Claude Code in git commit messages** — no `Co-Authored-By` trailer, no "Generated with" line, no mention in subject or body (USER 2026-09-25)
- **Never flip a daily file to `DAY CLOSED`** without an explicit close-day directive from the USER (see Day-close gate below)
- Never hard-code a Supabase project ref, DB host, QBO realmId or PBI workspace in code — use env vars / PBI parameters
- Never commit, print, or log secrets, API keys, OAuth tokens or connection strings; never move them out of `.env` / vaults. Never read `.env*` files (denied in `.claude/settings.json` on purpose)
- **QBO:** never call production QBO endpoints from tests or during development — sandbox and fixtures only; `ENV` defaults to `sandbox`. Scrub realmIds and tokens from every fixture before it lands in `fixtures/`
- **Money:** never convert amounts to float — Python `Decimal`, Postgres `numeric(15,2)`, end-to-end. Reject any float conversion in review
- **Reconciliation:** never "fix" a failing reconciliation by widening the tolerance ($0.01) — find the sign / mapping bug
- **Supabase:** never ship the `service_role` key or a DB password to the browser bundle, a PBIP file or a fixture; never expose `raw` / `stg` / mart tables through the Data API
- Never delete or rewrite pre-existing code, comments, or dead code that your change didn't orphan
- Never "improve" adjacent code, formatting, or naming outside the requested change
- Never add speculative features, abstractions, or configurability that wasn't asked for — spec §0 non-goals (cash-basis toggle, multi-currency, multi-entity consolidation, write-back) stay out
- Never run destructive operations (drops, deletes, truncates, `supabase db reset`, force-push, data purges) — propose the command, let the USER run it
- Never mark a task done without running its verification check (spec phase gates P1–P4)
- Never invent file paths, table names, or API shapes — verify against the repo, the spec and `supabase/migrations/` first

### Ask first (stop and confirm before acting)
- Any architectural choice → write/propose an ADR before implementing
- Cross-lane or ambiguous routing
- Schema/data-model changes beyond the explicitly requested scope (spec §2 is the contract)
- Introducing a new dependency, service, or MCP
- Anything touching auth, OAuth tokens, billing, permissions, or user data handling
- **Any write to a remote system**: applying migrations to the remote Supabase project (`supabase db push`), DML on remote tables, POSTs to the QBO sandbox (`seed_sandbox.py`), publishing / refreshing in the Power BI Service
- When multiple interpretations of a request exist — present them, don't pick silently
- When day-close intent is ambiguous → ask: "Close the day, or keep it open?"

---

## User communication rules

### ⭐ Active North Star — standing directive

> _Not locked yet._ When the USER locks the top-priority goals, record them here with the lock date, keep an amendment trail, and mirror them in `.log/features_and_decisions.md`. Candidate source: spec §8 (Definition of Done).
>
> **Carry rule (active once goals are locked):** surface the goals at session start, and reproduce the North Star block near the top of EVERY next-day `.log/plan/*` draft and EVERY `.log/daily/*` summary. Retire the directive when USER says the goals are met (or explicitly asks to retire it).

### At session start
- Check current date against file names and make sure to use the current date to plan and do the work
- Read last `.log/coms` file, last `.log/daily` summary, current day's + one previous + one future plan in `.log/plan` (i.e. prev day plan + current day plan + tomorrow day plan)
- If any of `.log/coms`, `.log/daily`, `.log/plan` is missing or malformed (wrong date format, missing required headings, empty file) → notify user, ask what to do

### During session
- For obvious routing (single-file edit in one lane), proceed with that lane's skills
- For ambiguous or cross-lane work, propose the lane(s) and ask
- Log every user request + ultra-brief response summary into `.log/coms`; tag entries with `#decision`, `#bug`, `#adr`, `#blocker` where relevant
- Tag idea/decision/feature mentions inline in `.log/coms` with `#idea`, `#decision`, `#feature` (alongside the existing `#bug` / `#adr` / `#blocker`) so they grep-retrieve cleanly at EOD for the `features_and_decisions.md` mirror step
- If a decision looks ADR-worthy, flag it inline ("this looks ADR-worthy") — don't wait for end-of-session
- After any code change, output git commands as a single fenced bash block, ready to copy-paste. Do not execute. Do not touch the working tree:
```bash
  git add "<paths>"
  git commit -m "<type>: <message>"
  git push
```
- When compiling `git add` commands: double-check syntax & make sure paths of files are wrapped in quotes

### At session end

**Day-close gate (load-bearing)**:
- **Default = DAY STAYS OPEN.** A session ending is NOT the same as the day ending.
- **NEVER mark a daily file `DAY CLOSED` unless the USER clearly and explicitly asks for end-of-day closure.** Explicit close-day phrases: "close the day", "end of day", "wrap up the day", "EOD ritual", "shut it down", or similar unambiguous closure directive. **Implicit / ambiguous phrases that do NOT count as close-day**: "log work", "update logs", "pause", "report back", "save state", "summarize today", "what's the status", or any request to mirror / log / report without explicit closure language.
- **When unsure: ASK the user explicitly** ("Close the day, or keep it open?") before flipping a daily file to `DAY CLOSED`. Do not assume.
- Logging work in coms / daily / plan during a session is INDEPENDENT of day-close. Mid-session log updates are normal; flipping the daily's `DAY OPEN` → `DAY CLOSED` header is a one-way ratchet that requires explicit USER consent.

**On confirmed day-close only** (USER explicitly requested):
- Write `.log/daily/daily-{yyyy-mm-dd}.md` (bullet-point summary, dry), then write `.log/plan` for next day (work done today + user-preferred next actions)
- Every `.log/daily/daily-{yyyy-mm-dd}.md` MUST include an `## Ideas / Decisions / Features delta` section summarizing today's additions (or `_(no delta today)_` if empty)
- After the daily file is written, mirror the delta into `.log/features_and_decisions.md` — add new idea blocks, append new decisions, flip feature states (`planned → implemented`). Skip if delta is empty.
- When finishing the day off: compile a new plan for the next day (notify user); next-day plan should consider work done for the current day + user-preferred actions for the next day
- Surface any ADR candidates flagged during the day for confirmation
- Run coms compaction check: count day-coms files in `.log/coms/` whose date is older than today. If >7, perform the compaction described in `## Logging routine` (oldest 7 → one themed compact file → delete sources).
- Always check file structure (presence and consistency) for: `.log/coms`, `.log/daily`, `.log/plan`
- Keep main log files clean and accurate: `.log/coms`, `.log/daily`, `.log/plan`

**On mid-session log update (DAY STAYS OPEN)**:
- It is fine to append to coms / refresh daily content / refresh next-day plan without flipping the daily header to `DAY CLOSED`. Keep the daily's "DAY OPEN" / "DAY KEPT OPEN" status intact unless the USER explicitly closes the day.

---

## Logging routine

- Daily coms: `.log/coms/coms-{yyyy-mm-dd}.md` — every user request + brief response
- Daily summary: `.log/daily/daily-{yyyy-mm-dd}.md` — bullet-point implementations, dry
- Plans: `.log/plan/plan-{yyyy-mm-dd}.md` — one file per day
- Weekly summary: `.log/weekly/weekly-{yyyy-Www}.md` — bullet-point implementations, comment section for describing issues, findings, ideas captured during the week; this file extends the semantic picture of a past week with more details via plain text
- Tag conventions in coms files: `#decision`, `#bug`, `#adr`, `#blocker` (for grep retrieval)
- Weekly rollup: last working day of the week, append a 5-line summary to `.log/weekly/weekly-{yyyy-Www}.md` linking back to daily files
- Coms compaction (evening housekeeping): if `.log/coms/` holds more than 7 day-coms files older than today, compact the oldest 7 into a single file named `coms-compact {first-date}_{last-date} — {theme-slug}.md`. For each request inside: one-sentence user essence + one-sentence AI response summary, as a bullet under a `## {yyyy-mm-dd}` heading. Theme slug summarizes the dominant work of the window (e.g. `scaffold-to-engine-factory`). Preserve `#decision` / `#bug` / `#adr` / `#blocker` tags inline — they are grep anchors. After the compact file is written and verified, hard-delete the 7 source day-coms files — full detail still lives in `.log/daily/`. Compact files are not counted as "old day-coms" for the next pass.
- File-structure consistency check (run at session start): correct date format, file-per-day, required headings present
- Features & decisions tree: `.log/features_and_decisions.md` — human-readable `idea → decisions → features` read-through of the ADR ledger (`.docs/ADR/`). Holds future plans on top of historical record. Updated daily in lockstep with `.log/daily/`.
- Anti-patterns catalogue: `.docs/ADD/anti-patterns.md` — codified recurring failure shapes. Candidates surface in daily summaries with `CAND-NNN` IDs; promote to the catalogue on second sighting (or single high-cost hit by judgment). Consult before reviewing code that touches a known anti-pattern's surface.
- When writing / composing future plans (files), always clearly state that the file is a draft in projection state at the very start of the file contents

---

## Universal conventions

### Naming (all lanes)
- Docs and scripts: `kebab-case.{md,ps1,sql}`. Exceptions where the ecosystem or the spec rules: Python modules `snake_case.py` (spec names `qbo_sync`, `generate_synthetic.py`, `seed_sandbox.py`); React components `PascalCase.tsx`, hooks `useCamelCase.ts`; Supabase migrations as the CLI names them (`<timestamp>_<name>.sql`); PBIP folders exactly as Desktop writes them
- Env vars / parameters: `SCREAMING_SNAKE_CASE`; client-safe values explicitly prefixed for the web build tool (`VITE_` if Vite — see ADR-0005)
- DB objects: `snake_case`, **names exactly as spec §2** (`raw_entity`, `stg_*`, `dim_*` singular, `fact_*`, `vw_*`, `sync_state`, `qa_reports_snapshot`) — the spec's "create exactly" beats the generic plural-table rule
- Branches: `prod` and `dev` only — no feature branches. Commit messages keep the conventional types (`feat:`, `fix:`, `chore:`, `docs:`)

### Branching & CI

- `prod` (production) ← `dev` — amended by USER 2026-09-25: **no feature branches**. All work is committed on `dev`; `dev` is merged into `prod` regularly. `prod` receives merges from `dev` only, never direct commits. `prod` is the GitHub default branch
- Merge `dev` → `prod` at points where the checks are green (tests, `validate.py`, phase gates). Suggest a merge when a checkpoint is reached; the USER runs it. `--ff-only` fails loudly if `prod` ever got a commit that is not on `dev`:
```bash
  git switch prod
  git pull
  git merge --ff-only dev
  git push
  git switch dev
```
- Preview deploys from `dev`, production deploys from `prod`, where the platform supports it (web report)
- CI: lint (ruff / eslint) → typecheck (TS strict) → build → test (pytest for the ETL; `dbt build` with one test per `DetailType` on fixtures) → SQL tests (validation V1–V3 on a disposable DB) → PBIP validation
- Migration gate: every PR touching `supabase/migrations/` must apply cleanly on a fresh database

### Testing policy
- **All manual / smoke / click-test runs happen on the deploy target** (remote Supabase dev project · Power BI Service test workspace · web preview deploy) — not against localhost / Desktop-only state — unless a heavy need for local testing arises (e.g., debugging an OS-only failure, isolating a build-tool issue, or when no deploy exists yet). Reason: parity with the deploy environment, no local-version drift, no host-only quirks.
- Automated tests (pytest; web: Vitest) still run locally and in CI as usual; the rule above applies to **manual end-to-end / interactive verification only**.
- QBO calls in tests: captured sandbox fixtures only. Live calls: sandbox only, and only in explicit sandbox runs (phase gates P1, P3).

### Languages / locales supported
en-US, USD — UI + content locked together at MVP. Single currency by design (multi-currency is a spec §0 non-goal). Number format per spec §6: `$K` 0–1 dp, % 1 dp, tabular figures.

---

## Data platform conventions (ETL + Supabase)

**Stack:** Python 3.12 · QBO Accounting API v3 (`minorversion=75`) · Supabase Postgres · Supabase CLI migrations · transforms in dbt-core + dbt-postgres, DDL / init code in migrations (ADR-0002) · pytest

**Structure:**
```
etl/          → qbo_sync CLI (auth · backfill · cdc · status), generate_synthetic.py, seed_sandbox.py, tests/
fixtures/     → scrubbed sandbox JSON, one file per entity and per Line DetailType
demo_data/    → synthetic CSVs (24 months, deterministic seed) + loader
supabase/     → created by `supabase init`; migrations/ hold ALL DDL / init code (schema `qbo`, roles, grants, tables, functions)
dbt/          → dbt project `qbo_pnl`: builds stg_* / vw_* views, fills the migration-owned dim_* / fact_* (ADR-0002)
```

**Key rules:**
- Spec §1 QBO facts are hard constraints: one entity per query, no joins/OR/GROUP BY, `STARTPOSITION`/`MAXRESULTS 1000`, `ORDERBY Id` on backfill, CDC max 30-day lookback with 10-minute watermark overlap (gap > 30 d → re-backfill), 429 → exponential backoff (base 2 s, max 5 retries, jitter), ≤ 500 req/min, ≤ 10 concurrent
- **Refresh token rotates on every use** → persist the new token atomically (transaction + row lock) *before* using it; never refresh concurrently (single-flight)
- Config only via env / `.env`: `CLIENT_ID`, `CLIENT_SECRET`, `REALM_ID`, `DB_URL`, `ENV=sandbox|prod` (spec §4 P1)
- Money: `json.loads(..., parse_float=Decimal)`; `numeric(15,2)` in Postgres. Dates: QBO local dates → `date`; timestamps → `timestamptz` (UTC)
- Raw zone is immutable: insert-only landed JSON (`jsonb`)
- Transforms are deterministic and re-runnable: full-refresh safe + incremental upsert path; running twice yields identical row counts (gate P2)
- Line explosion (spec §3.1) and sign normalization (spec §3.2) are the correctness core: one unit test per `DetailType`, built on `fixtures/`
- Voided → `is_voided`; deleted (CDC only) → `is_deleted`; `vw_fact_gl` filters both out
- Every schema change is a migration (`supabase migration new <name>`); no ad-hoc DDL on the remote project
- Validation (spec §5): V1 reconciliation vs Reports API per month × `stmt_section`, tolerance $0.01, fail loudly; V2 unmapped accounts; V3 orphans / dead letters
- Prefer warehouse SQL over Power Query or React code for any transform logic (spec §9.6)

**Database conventions:**
- **Tenancy (amended USER 2026-09-25 — ADR-0008):** the Supabase project `vosk.dev` is **shared** — it is the USER's personal web-app backend and hosts other schemas that will grow. The rule "one Supabase project per client" is dropped. QBO lives in its **own schema, `qbo`** (ADR-0003); objects without a schema (roles, pg_cron jobs) take a `qbo_` prefix. Never create, alter, grant on or drop anything outside the QBO namespace; project-wide settings (Data API exposed schemas, extensions, auth, network) are shared → ask first. One QBO realm per deployment; multi-entity consolidation is a non-goal
- **Keys:** integer `identity` surrogate keys as spec §2 defines them. The web-app "UUID PKs" rule does not apply to warehouse tables — they are internal and never used in URLs
- **Money:** `numeric(15,2)`; never `float` / `real` / `double precision`
- **Soft-delete:** facts carry `is_voided` / `is_deleted` flags (spec); raw zone is append-only
- **Exposure + roles (ADR-0003, proposed):** schema `qbo` is not exposed through the Data API, and nothing is granted to `anon` / `authenticated`. ETL + dbt write as `qbo_etl` (no DDL rights on tables); Power BI reads `vw_*` only, as `qbo_reader`. The web report's API path (exposed schema with `security_invoker` views, or RPC) is decided with ADR-0005
- **Connections:** Windows clients (Power BI, local Python) connect through the Supabase **session pooler** (IPv4); the direct host is IPv6-only without the IPv4 add-on. SSL required

---

## Track-specific conventions

### ▶ TRACK C — BI development (Power BI, PBIP format)

**Stack:** Power BI Desktop (PBIP enabled; PBIR report format; TMDL model) · DAX · Import mode · source: Supabase Postgres serve views `vw_*` (PostgreSQL connector) · deployment to a Power BI Service / Fabric workspace (not assigned yet)

**Structure:**
```
PNL/                                → report project folder (code PNL)
  <Report Name>.SemanticModel/      → TMDL model definition (tables, measures, relationships, roles)
  <Report Name>.Report/             → PBIR report definition (pages, visuals)
  <Report Name>.pbip
.docs/model/                        → star-schema diagram, measure dictionary, refresh strategy
```
The PBIP files do not exist yet: Desktop creates them via File → Save as → Power BI project. Keep the folder names exactly as Desktop writes them.

**Key rules:**
- PBIP is the source of truth — every model/report change lands as a diff-reviewable PBIP commit; no binary `.pbix` in the repo. The spec's `.pbit` and demo `.pbix` (spec §4 Phase 4) are release artifacts exported from the PBIP, not sources
- The model reads **serve views only** (`vw_fact_gl`, `vw_dim_account`, `vw_dim_date`, `vw_dim_class`, `vw_fact_budget` — spec §2.4); never raw / stg / base tables
- Parameters `Server`, `Database`, `FY_START` (spec §4); FY_START tested with 1 and 7 (spec §8)
- Star schema discipline: fact and dimension tables explicitly classified; single-direction 1→* relationships; date table marked; no snowflaking without an ADR; no bidirectional relationships without an ADR
- All measures live in dedicated measure tables/folders — no implicit measures, no measures scattered on fact tables. Spec §7 is the starting measure pack; the P&L matrix uses the `pnl_layout` disconnected table + `SWITCH` measure (spec §6)
- Measure dictionary in `.docs/model/` stays in lockstep with the model: name, plain-language definition, DAX, owner. The web report's KPI definitions point at the same entries
- DAX and SQL follow the house formatting style (`dax-sql-formatter`) — applied silently and always
- Power Query: query folding preserved wherever possible; every folding-breaking step is commented with rationale
- RLS: not in v1 (one client per deployment). Introducing roles is ADR-worthy; roles then live in TMDL, are documented in `.docs/model/`, and tested with "View as" before every deploy
- Incremental refresh policies and aggregations are ADR-worthy decisions (not needed at v1 volume: < 2 min refresh @ 3K transactions, spec §8)
- Naming: model tables `PascalCase` (dims prefixed `Dim`, facts `Fact` — e.g. `vw_fact_gl` → `FactGL`; spec §7 says "refine names to house style") · measures human-readable with folder paths · columns `PascalCase` · hide all raw FK/key columns from report view
- No calculated columns where a Power Query step or upstream view can do the job — push transforms upstream
- Report performance budget: 12 visuals per page max (spec §6 single page); Performance Analyzer run before merging heavy pages
- PBIR only (`definition/` folder, `definition.pbir` version 4.0+). No PBIR-Legacy edits (`report.json`) — if found, flag it; the upgrade happens in Desktop only

**PBIP file handling (agent kit):**
- `*.pbix` / `*.pbit` exports are **read-only backups or release artifacts**: never edit, parse or "fix" them. `*.pbix` is gitignored; exports go to `PNL/__backup__/` (gitignored)
- `.pbi/cache.abf` is a full local copy of the model **data** — it must never reach the remote (ignored at any depth). Other `.pbi/*.json` may be tracked; `localSettings.json` one-line diffs from another machine are noise
- All file edits go through the **pbip-editor** workflow: locate → read → surgical edit → validate. Preserve `name`, `lineageTag`, `queryRef` and `$schema` versions byte-for-byte unless the task is the rename itself
- Model-scope beats visual-scope: when a fix could live in the theme or the model instead of many `visual.json` overrides, propose that first
- Verification: `python _scripts/validate.py` green (JSON parse, encoding, TMDL tabs), `powerbi-report-author validate` for PBIR, then render-check in Desktop (open the `.pbip`) — Desktop is the final validator
- Design tokens (spec §6) are canonical for PBI **and** web: Segoe UI; ink `#1F2733` on white; positive `#188038` / negative `#C5221F` only on variance elements; reference grey `#9AA4AF` (PY solid, Budget dotted); expense rows invert variance sentiment

**Deployment:**
- `production workspace` ← `test workspace` ← dev (Desktop)
- Deploy tool not chosen yet (Fabric deployment pipelines / Fabric CLI `fab`) — decide in ADR-0006 together with the Service refresh path; manual publishes to production are prohibited
- Post-deploy checks: refresh succeeds; matrix totals reconcile with QBO ProfitAndLoss to $0.01 (spec §8)

### ▶ Web report (React) — second consumer

**Stack:** React · TypeScript strict · `@supabase/supabase-js` · plotting library, build tool and hosting not chosen yet (ADR-0005)

**Structure:**
```
web/          → React app (created by the scaffold tool chosen in ADR-0005)
```

**Key rules:**
- Reads serve-layer views only, through supabase-js with the anon / publishable key under RLS. The `service_role` key never enters `web/`
- No business logic or money arithmetic in components: every number shown is a column of a serve view; JS only formats. A KPI that disagrees with the PBI measure of the same name is a bug
- TypeScript strict; ESLint + Prettier; URL params and filter inputs validated at the boundary (Zod, `.strict()`)
- Client env limited to the Supabase URL and anon key (prefixed per build tool)
- Charts follow the spec §6 tokens and the same period / comparison semantics as the PBI page (Month | QTD | YTD; vs PY | vs Budget)

---

## Before you code

1. Read the relevant spec section (`.docs/qbo-pnl-project-spec.md`) and feature spec in `.docs/ADD/features/`
2. Check `.docs/ADD/tech-stack.md` for where the change fits
3. Check `.docs/ADR/` for any ADRs that constrain your approach
4. If making an architectural choice, write a new ADR before implementing

### Core coding rules

#### 1. Think Before Coding
Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

#### 2. Simplicity First
Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.
- Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

#### 3. Surgical Changes
Touch only what you must. Clean up only your own mess.

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

#### 4. Goal-Driven Execution
Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]

---

## Available skills

- **pbip-editor** — use it for **every** report/model edit done on files (measures, visual design attributes, visual calculations, batch changes, structure questions); `references/m-language.md` for Power Query M.
- **dax-sql-formatter** — house formatting style; applies silently to **every** SQL statement and DAX expression written or shown. Do not modify.
- Microsoft skills (microsoft/skills-for-fabric, pinned commit in `pbi-fabric-agent-kit/MANIFEST.md`; refreshed only by `scripts/sync-pbi-fabric-skills.ps1`). Shared files live in `.claude/common/`.
  - **In use:** `semantic-model-authoring` (model design, DAX, deploy, refresh), `powerbi-report-cli` (report planning → design → authoring → publish), `search-consumption-cli` (find items across workspaces).
  - **Dormant — do not route work to them:** `sqldw-cli`, `spark-cli`, `sqldb-cli`, `onelake-catalog-govern-cli`. The warehouse is Supabase, not Fabric (ADR-0001); they apply only if an ADR moves storage into Fabric.
- Where a Microsoft skill says to edit without asking, skip backups, re-serialise whole files, treat TMDL on disk as stale, delete duplicate items, or run destructive git commands, **Rule #1 and pbip-editor win**.
- Known issues of the bundled skills are listed in `pbi-fabric-agent-kit/MANIFEST.md` → "Known issues"; they are upstream and expected — don't edit copied Microsoft skill files.

<!-- BEGIN pbi-fabric-agent-setup -->
## Power BI & Fabric agent setup

The skills in `.claude/skills` were installed from pbi-fabric-agent-kit 2026-09-25. Skip any
`check-updates` step the skills ask for; updates happen by re-running `scripts/sync-pbi-fabric-skills.ps1`.

### Tool routing
- Model changes (local or cloud): `powerbi-modeling` MCP server. Local = Power BI Desktop / PBIP;
  cloud = connect to the workspace model. Changes made through the MCP land in Desktop's memory:
  they reach the TMDL files only when Desktop saves.
- DAX: write through MCP, check with DAX test queries, format per dax-sql-formatter.
- Reports (PBIR): powerbi-report-cli, modes planning → design → authoring.
  Validate with `powerbi-report-author validate`; check with `powerbi-desktop screenshot`.
  `powerbi-desktop reload` discards unsaved Desktop edits and reloads PBIR only: run
  `powerbi-desktop status` first and never reload while `hasUnsavedChanges` is true.
- Publish / update / download reports in the Service: powerbi-report-cli, management mode.
- Warehouse SQL: **Supabase Postgres** — `db-schema-architect` (design), `pg-sql-dev` (queries),
  `pg-sqldev` MCP for catalog facts once registered. Not sqldw-cli / spark-cli / sqldb-cli.
- Create/delete items, workspace & item access, item details: Fabric CLI (`fab`); see `fab --help`.
- Find items across workspaces: search-consumption-cli.
- Power Query M: pbip-editor (see references/m-language.md).

### Safety
- Ask me before: deleting any item; changing permissions or RLS role members; refreshing or
  deploying to production; writing to the Supabase database, the QBO sandbox or any cloud item.
  Name the workspace / project and item when you ask.
- Check read-only first. Show the exact command before running anything that changes the cloud.
- Never print, log or store access tokens or secrets.
- Report work requires PBIP. I save in Desktop before you edit PBIR files.
<!-- END pbi-fabric-agent-setup -->