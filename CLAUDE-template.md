# {{PROJECT_NAME}} — AI Coding Instructions

> This file is for AI coding assistants working on the {{PROJECT_NAME}} codebase.
> It contains pointers, user communication rules, logging routine, critical rules, and conventions (product spec lives in `docs/`).

<!-- ─────────────────────────────────────────────────────────────
HOW TO INSTANTIATE THIS TEMPLATE
1. Replace every {{PLACEHOLDER}}.
2. Pick ONE project track in "Track-specific conventions" (WEB / MOBILE / BI-PBIP) and delete the other two.
3. Fill the Orchestration map with your actual sub-agents (or delete the section for single-agent projects).
4. Write your North Star goals (or delete the block until goals are locked).
5. Delete all instantiation comments like this one.
Universal blocks (keep as-is for any project): Critical rules · Session start/during/end ·
Logging routine · Before you code · Core coding rules.
───────────────────────────────────────────────────────────── -->

## Project identity

- **Project name**: {{PROJECT_NAME}}
- **One-line purpose**: {{WHAT_THIS_PROJECT_IS_FOR}}
- **Canonical domain / workspace**: {{DOMAIN_OR_WORKSPACE}} <!-- web: yourapp.com · mobile: store listing / bundle id · BI: Fabric/PBI workspace name -->
- **Public surface/URL**: {{PUBLIC_SURFACE}} <!-- landing page URL · app store page · published report link -->
- **Runtime hook**: {{CANONICAL_ENV_VAR_OR_PARAM}} is the canonical source of truth at runtime; do NOT hard-code the domain/workspace in code. The string above is for docs/copy/UX-text only.

---

## Quick navigation

| What | Where |
|------|-------|
| Global project overview & summary | `docs/{{project-slug}}-ai-coding-brief.md` |
| Product overview | `docs/product/overview.md` |
| Application Design documents (ADD) | `docs/ADD/` |
| Architecture Decision Documents (ADRs) | `docs/ADR/` |
| Feature specs | `docs/ADD/features/` |
| Tech stack + rationale | `docs/ADD/tech-stack.md` |
| Anti-patterns catalogue (codified bug-class memory) | `docs/ADD/anti-patterns.md` |
| Features plan, log of implementation, user idea stash | `.log/features_and_decisions.md` |
| Raw ideas / parking lot | `docs/ADD/ideas/ideas.md` |

---

## Orchestration map

<!-- Delete this whole section for single-agent projects. -->

Main agent ({{MAIN_AGENT_MODEL}}) routes work to sub-agents. Auto-route obvious cases. Ask the user only when the request spans two agents or routing is genuinely ambiguous. Main agent does not write code — it routes, sequences, verifies. Prioritize sub-agent utilization.

### Sub-agents

| Agent | Owns | Auto-route triggers | Defers to | Short name |
|-------|------|---------------------|-----------|------------|
| {{AGENT_1}} | {{OWNERSHIP}} | {{TRIGGERS: keywords, file globs}} | {{DEFERS_TO}} | {{NICK}} |
| {{AGENT_2}} | {{OWNERSHIP}} | {{TRIGGERS}} | {{DEFERS_TO}} | {{NICK}} |
| {{AGENT_3}} | {{OWNERSHIP}} | {{TRIGGERS}} | {{DEFERS_TO}} | {{NICK}} |
| {{AGENT_4}} | {{OWNERSHIP}} | {{TRIGGERS}} | {{DEFERS_TO}} | {{NICK}} |

### Skills per agent
- **{{AGENT_1}}:** {{SKILL_LIST}}
- **{{AGENT_2}}:** {{SKILL_LIST}}
- **{{AGENT_3}}:** {{SKILL_LIST}}
- **{{AGENT_4}}:** {{SKILL_LIST}}

### MCP access
- **{{MCP_1}} ({{purpose}}):** {{agents allowed}}
- **{{MCP_2}} ({{purpose}}):** {{agents allowed}}
- Do not add MCPs to agents outside this matrix without an ADR.

### Roster discipline
{{N}} sub-agents is the target. Cross-cutting concerns (security, perf, i18n, accessibility) live as checklists inside the relevant agent — not as new agents.

---

## ⛔ Critical rules — allowed / prohibited actions

These rules are load-bearing. They override convenience, speed, and any implicit inference from context. When a rule conflicts with a user request, surface the conflict — don't silently pick a side.

### Always allowed (no permission needed)
- Reading any file in the repo, docs, logs, and ADRs
- Appending to `.log/coms` during a session; refreshing daily / plan content while the day stays OPEN
- Proposing plans, flagging ADR candidates, surfacing risks and simpler alternatives
- Auto-routing single-lane work to the owning sub-agent
- Compiling ready-to-paste command blocks (git, deploy, CLI) for the user to run

### Prohibited (never do, even if it seems helpful)
- **Never execute git commands or touch the working tree state** — output git commands as a single fenced bash block, ready to copy-paste; nothing more
- **Never flip a daily file to `DAY CLOSED`** without an explicit close-day directive from the USER (see Day-close gate below)
- Never hard-code the canonical domain/workspace in code — use {{CANONICAL_ENV_VAR_OR_PARAM}}
- Never commit, print, or log secrets, API keys, or connection strings; never move them out of env/config vaults
- Never delete or rewrite pre-existing code, comments, or dead code that your change didn't orphan
- Never "improve" adjacent code, formatting, or naming outside the requested change
- Never add speculative features, abstractions, or configurability that wasn't asked for
- Never run destructive operations (drops, deletes, resets, force-push, data purges) — propose the command, let the USER run it
- Never mark a task done without running its verification check
- Never invent file paths, table names, or API shapes — verify against the repo/docs first

### Ask first (stop and confirm before acting)
- Any architectural choice → write/propose an ADR before implementing
- Cross-agent or ambiguous routing
- Schema/data-model changes beyond the explicitly requested scope
- Introducing a new dependency, service, or MCP
- Anything touching auth, billing, permissions, or user data handling
- When multiple interpretations of a request exist — present them, don't pick silently
- When day-close intent is ambiguous → ask: "Close the day, or keep it open?"

---

## User communication rules

### ⭐ Active North Star — standing directive

<!-- Fill with the current locked goal set, or delete until goals are locked. Keep the amendment trail — it is the audit log of scope evolution. -->

> The **{{N}} top-priority goals** are the single driving force of all product development right now. Locked by USER {{DATE}}; amended {{DATE}} ({{what changed}}). Canonical definition: this section (mirrored in `.log/features_and_decisions.md`).
>
> **(1)** {{GOAL_1}}. **(2)** {{GOAL_2}}. **(3)** {{GOAL_3}}. {{…}}
>
> **Carry rule:** surface these goals at session start, and reproduce the North Star block near the top of EVERY next-day `.log/plan/*` draft and EVERY `.log/daily/*` summary. Retire the directive when USER says the goals are met (or explicitly asks to retire it).

### At session start
- Check current date against file names and make sure to use the current date to plan and do the work
- Read last `.log/coms` file, last `.log/daily` summary, current day's + one previous + one future plan in `.log/plan` (i.e. prev day plan + current day plan + tomorrow day plan)
- If any of `.log/coms`, `.log/daily`, `.log/plan` is missing or malformed (wrong date format, missing required headings, empty file) → notify user, ask what to do

### During session
- For obvious routing (single-file edit in one agent's lane), auto-route and proceed
- For ambiguous or cross-agent work, propose the agent and ask
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
- Weekly summary: `.log/weekly/weekly-{yyyy-Www}.md` — bullet-point implementations, comment section for describing issues, findings, ideas captured during the week; this file extends the semantic picture of a past week with more details via plain text
- Tag conventions in coms files: `#decision`, `#bug`, `#adr`, `#blocker` (for grep retrieval)
- Weekly rollup: last working day of the week, append a 5-line summary to `.log/weekly/weekly-{yyyy-Www}.md` linking back to daily files
- Coms compaction (evening housekeeping): if `.log/coms/` holds more than 7 day-coms files older than today, compact the oldest 7 into a single file named `coms-compact {first-date}_{last-date} — {theme-slug}.md`. For each request inside: one-sentence user essence + one-sentence AI response summary, as a bullet under a `## {yyyy-mm-dd}` heading. Theme slug summarizes the dominant work of the window (e.g. `scaffold-to-engine-factory`). Preserve `#decision` / `#bug` / `#adr` / `#blocker` tags inline — they are grep anchors. After the compact file is written and verified, hard-delete the 7 source day-coms files — full detail still lives in `.log/daily/`. Compact files are not counted as "old day-coms" for the next pass.
- File-structure consistency check (run at session start): correct date format, file-per-day, required headings present
- Features & decisions tree: `.log/features_and_decisions.md` — human-readable `idea → decisions → features` read-through of the ADR ledger (`docs/architecture/decisions/`). Holds future plans on top of historical record. Updated daily in lockstep with `.log/daily/`.
- Anti-patterns catalogue: `docs/architecture/anti-patterns.md` — codified recurring failure shapes. Candidates surface in daily summaries with `CAND-NNN` IDs; promote to the catalogue on second sighting (or single high-cost hit by judgment). Consult before reviewing code that touches a known anti-pattern's surface.
- When writing / composing future plans (files), always clearly state that the file is a draft in projection state at the very start of the file contents

---

## Universal conventions

### Naming (all tracks)
- Files: `kebab-case.{{ext}}`
- Env vars / parameters: `SCREAMING_SNAKE_CASE`; public/client-safe values explicitly prefixed ({{e.g. NEXT_PUBLIC_}})
- DB tables: `snake_case`, plural
- Branches: `{{type}}/{{short-description}}` (`feat/`, `fix/`, `chore/`)

### Branching & CI

<!-- `dev` ← `FEATURE_N` ask if user needs these branches at project init run -->

- `prod` (production) ← `dev` ← {{FEATURE_N}}
- Preview/staging deploys on PRs where the platform supports it
- CI: lint → typecheck → build → test
- {{ADDITIONAL_CI_GATES}} <!-- e.g. type regen gate on migrations, PBIP validation, store build checks -->

### Testing policy
- **All manual / smoke / click-test runs happen on the deploy target** ({{preview env / TestFlight-internal track / PBI Service workspace}}) — not against localhost / Desktop-only state — unless a heavy need for local testing arises (e.g., debugging an OS-only failure, isolating a build-tool issue, or when no deploy exists yet). Reason: parity with the deploy environment, no local-version drift, no host-only quirks.
- Automated tests ({{unit/integration framework}}) still run locally and in CI as usual; the rule above applies to **manual end-to-end / interactive verification only**.
- {{TRACK_SPECIFIC_GAUNTLET}} <!-- e.g. full typecheck+lint+test+build before push on router-touching changes -->

### Languages / locales supported
{{LOCALES}} — UI + content locked together at MVP.

---

## Track-specific conventions

<!-- ═══ KEEP EXACTLY ONE TRACK BELOW. DELETE THE OTHER TWO. ═══ -->

### ▶ TRACK A — Web app development

**Stack:** {{e.g. Next.js (App Router) · TypeScript strict · Supabase (Postgres + Auth + RLS) · Zod · background jobs via {{Inngest/queue}} · Vercel}}

**Structure:**
```
apps/web/          → app shell (thin — orchestration only)
packages/engine/   → core business logic (services, adapters, models)
packages/shared/   → schemas + API types (consumed by all clients)
{{db}}/            → migrations + seed data
{{jobs}}/          → background job functions
```

**Key rules:**
- TypeScript strict mode everywhere; ESLint + Prettier with shared config
- All inputs validated at the boundary ({{Zod, `.strict()` — reject unknown fields}}) before reaching any service
- No business logic in frontend components — engine is the single source of truth
- Every external provider (AI, payments, email) sits behind an adapter interface — swapping is a config change, not a refactor
- Engine services take clients via constructor (DI) — no global singletons
- Every metered external call logs a usage row (provider, model, tokens, cost, latency)
- Content moderation / input sanitation runs BEFORE any generation or mutation call, not only after
- Long-running work goes async via {{job runner}} — never hold an HTTP request open 30+ seconds
- After applying any DB migration, regenerate types ({{command}}); CI gates PRs touching migrations on a fresh regen
- Components: `PascalCase.tsx` · services: `PascalCase` classes with DI · API routes: `/api/v1/{resource}` — RESTful, lowercase, plural nouns

**Database conventions:**
- **Tenancy:** {{single-tenant via auth user id / org-tenant via org_id}}. Standard ownership FK: `user_id uuid references auth.users(id) on delete cascade` for user-content tables; `on delete set null` for telemetry/audit (preserves history past account deletion); `on delete restrict` for identity-anchor rows (prevents accidental deletion cascades)
- **IDs:** UUID v4 via `gen_random_uuid()` for all PKs. Never expose `SERIAL`/`BIGSERIAL` in URLs or public APIs (enumerable IDs leak business volume)
- **Money:** `numeric(10,6)` for sub-cent unit costs (usage telemetry); `*_cents BIGINT` for transactional billing. Never `float` for money
- **Soft-delete:** `deleted_at timestamptz` on user-content tables. Ledger/event tables are append-only or hard-delete by design — no `deleted_at` there
- **Service-role-only tables:** RLS-enabled with zero policies where only the backend writes — denies all `anon`/`authenticated` reads while `service_role` bypasses. Document + smoke-test the invariant

### ▶ TRACK B — Mobile app development

**Stack:** {{e.g. React Native + Expo (managed) · TypeScript strict · shared packages with web · Supabase/Firebase backend · EAS Build/Submit}}

**Structure:**
```
apps/mobile/       → app shell (screens, navigation — thin)
packages/engine/   → core business logic (shared with other clients)
packages/shared/   → schemas + API types
{{native}}/        → native modules / config plugins (only when unavoidable)
```

**Key rules:**
- TypeScript strict mode everywhere; ESLint + Prettier with shared config
- No business logic in screens/components — engine/shared packages are the single source of truth
- All API boundaries validated with shared schemas — mobile consumes the same types as web
- Navigation map is documented in `docs/architecture/app_nav_map.md` and is the single source of truth for screen flow
- Every store-facing change (icons, permissions, entitlements, deep links, push config) is flagged explicitly — store review is a deploy gate, not an afterthought
- Secrets live in {{EAS secrets / native keychain config}} — never in the JS bundle
- Offline behavior stated per feature: {{cache-first / online-only / queue-and-sync}} — no implicit assumptions
- OTA updates ({{Expo Updates}}) for JS-only changes; native changes require a new build + store submission — call out which bucket every change falls in
- Screens: `PascalCase.tsx` · hooks: `useCamelCase.ts` · deep links: `{{scheme}}://{resource}/{id}`

**Release channels:**
- `production` (store) ← `staging` (TestFlight / internal track) ← dev builds
- Manual smoke testing happens on staging builds on real devices — not only in the simulator

### ▶ TRACK C — BI development (Power BI, PBIP format)

**Stack:** {{Power BI Desktop (PBIP enabled) · TMDL semantic model · DAX · Power Query/M · deployment to {{Fabric workspace / PBI Service}} · source: {{warehouse/lakehouse/SQL}}}}

**Structure:**
```
{{report-name}}.SemanticModel/   → TMDL model definition (tables, measures, relationships, roles)
{{report-name}}.Report/          → report definition (pages, visuals)
docs/model/                      → star-schema diagram, measure dictionary, refresh strategy
scripts/                         → Tabular Editor scripts, deployment helpers
```

**Key rules:**
- PBIP is the source of truth — every model/report change lands as a diff-reviewable PBIP commit; no binary `.pbix` in the repo
- Star schema discipline: fact and dimension tables explicitly classified; no snowflaking without an ADR; no bidirectional relationships without an ADR
- All measures live in dedicated measure tables/folders — no implicit measures, no measures scattered on fact tables
- Measure dictionary in `docs/model/` stays in lockstep with the model: name, plain-language definition, DAX, owner
- DAX and SQL follow the house formatting style — applied silently and always
- Power Query: query folding preserved wherever possible; every folding-breaking step is commented with rationale
- RLS roles defined in the model (TMDL), documented in `docs/model/`, and tested with "View as" before every deploy
- Incremental refresh policies and aggregations are ADR-worthy decisions — document parameters (`RangeStart`/`RangeEnd`) and partitions
- Naming: tables `PascalCase` (dims prefixed {{`Dim`}}, facts {{`Fact`}}) · measures human-readable with folder paths · columns `PascalCase` · hide all raw FK/key columns from report view
- No calculated columns where a Power Query step or upstream view can do the job — push transforms upstream
- Report performance budget: {{N}} visuals per page max; Performance Analyzer run before merging heavy pages

**Deployment:**
- `production workspace` ← `test workspace` ← dev (Desktop)
- Deploy via {{Fabric deployment pipelines / pbi-tools / Fabric CLI}}; manual publishes to production are prohibited
- Post-deploy checks: refresh succeeds, RLS verified per role, key measure totals reconciled against source

<!-- ═══ END OF TRACKS ═══ -->

---

## Before you code

1. Read the relevant feature spec in `docs/features/`
2. Check `docs/architecture/DESIGN.md` for where the change fits
3. Check `docs/architecture/decisions/` for any ADRs that constrain your approach
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
