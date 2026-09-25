# PROJECT SPEC: QBO → Power BI P&L Template
> **Purpose of this document:** self-contained project context for an AI coding assistant (Claude Code / Copilot / etc.). Contains everything needed to execute the build without external context. Follow phases in order. Each phase has acceptance criteria — do not proceed past a failed gate.

---

## 0. PROJECT BRIEF

**Goal:** build a productized, single-page Profit & Loss dashboard in Power BI, fed by QuickBooks Online (QBO) API data through an owned ETL pipeline, reusable across SME clients.

**Deliverables:**
1. Python extraction service (QBO API → warehouse)
2. SQL transform layer (raw → staging → mart star schema)
3. Synthetic demo dataset (CSV + sandbox-seeding script)
4. Power BI template (.pbit) — single-page P&L per layout spec in §6
5. Validation suite (reconciliation against QBO's own reports)

**Tech stack:** Python 3.12, PostgreSQL or Azure SQL (parameterize; support both), plain SQL or dbt-core for transforms, Power BI Desktop (Import mode).

**Non-goals (v1):** cash-basis toggle, multi-currency, multi-entity consolidation, write-back. Do not implement.

---

## 1. QBO API — FACTS & CONSTRAINTS (do not violate)

- **Base URLs:** prod `https://quickbooks.api.intuit.com/v3/company/{realmId}/` · sandbox `https://sandbox-quickbooks.api.intuit.com/v3/company/{realmId}/`
- **Auth:** OAuth 2.0 authorization-code flow. Access token TTL = 1h (refresh at ~50min). **Refresh token: ~100-day rolling, ROTATES ON EVERY USE** → persist new refresh token atomically (DB transaction + row lock) before using it. Never refresh concurrently.
- **Scope:** `com.intuit.quickbooks.accounting` (read-only usage; never request payments scopes).
- **Always append** `minorversion=75` (or current latest) to every call.
- **Query language:** `GET /query?query=<url-encoded>`. One entity per query. **NO joins, NO OR, NO GROUP BY** (COUNT only). LIKE supports `%` only. Id supports only `=`/`IN`. Pagination: `STARTPOSITION n MAXRESULTS 1000` (cap 1000); always `ORDERBY Id` during backfill.
- **Incremental:** `GET /cdc?entities=<list>&changedSince=<ISO>` — returns changed AND deleted (`status:"Deleted"`). **Max lookback 30 days** → sync daily; if gap > 30d, trigger full re-backfill of affected entities. Overlap watermark by 10 minutes.
- **Rate limits:** assume 500 req/min per realm, 10 concurrent. Implement exponential backoff on HTTP 429 (base 2s, max 5 retries, jitter).
- **Reports API:** `GET /reports/ProfitAndLoss?start_date=&end_date=&summarize_column_by=Month` → nested Rows/Columns JSON. Used ONLY for validation (§5).
- **Amounts:** DECIMAL(15,2). Never float. Dates: QBO returns local dates; store as DATE; timestamps as UTC.
- **Voided txns:** remain present with zeroed amounts → flag `is_voided`. Deletes: only visible via CDC → flag `is_deleted`.

---

## 2. WAREHOUSE SCHEMA (create exactly; ANSI-ish, adapt types per engine)

### 2.1 Raw zone (immutable landed JSON)
```sql
CREATE TABLE raw_entity (
  entity_type VARCHAR(30) NOT NULL,   -- 'Invoice','Bill','Account',...
  qbo_id      VARCHAR(20) NOT NULL,
  payload     JSONB/NVARCHAR(MAX) NOT NULL,
  synced_at   TIMESTAMP NOT NULL,
  PRIMARY KEY (entity_type, qbo_id, synced_at)
);
```

### 2.2 Dimensions
```sql
CREATE TABLE dim_account (
  account_key     INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  qbo_id          VARCHAR(20) UNIQUE NOT NULL,
  account_name    VARCHAR(200),
  fully_qualified VARCHAR(400),
  account_type    VARCHAR(50),
  account_subtype VARCHAR(80),
  classification  VARCHAR(20),   -- Asset|Liability|Equity|Revenue|Expense
  parent_qbo_id   VARCHAR(20),
  is_active       BOOLEAN,
  -- consultant-maintained mapping layer:
  stmt_section    VARCHAR(40),   -- Revenue|COGS|OpEx|OtherInc|OtherExp|Tax
  stmt_group      VARCHAR(80),   -- e.g. Payroll, Marketing, Rent
  stmt_sort       INT
);
CREATE TABLE dim_customer ( customer_key INT ... IDENTITY PK,
  qbo_id VARCHAR(20) UNIQUE, display_name VARCHAR(200),
  parent_qbo_id VARCHAR(20), is_active BOOLEAN, payment_terms VARCHAR(50));
CREATE TABLE dim_vendor   ( vendor_key INT ... IDENTITY PK,
  qbo_id VARCHAR(20) UNIQUE, display_name VARCHAR(200), is_active BOOLEAN);
CREATE TABLE dim_class    ( class_key INT ... IDENTITY PK,
  qbo_id VARCHAR(20) UNIQUE, class_name VARCHAR(120));
CREATE TABLE dim_date (
  date_key INT PRIMARY KEY,          -- yyyymmdd
  d DATE, y INT, q VARCHAR(2), m INT, month_name VARCHAR(12),
  year_month VARCHAR(7), fiscal_year INT, fiscal_period INT,
  week_start DATE, is_month_end BOOLEAN
);  -- FY start month = parameter FY_START (default 1)
```

### 2.3 Facts
```sql
CREATE TABLE fact_gl (
  gl_key BIGINT ... IDENTITY PRIMARY KEY,
  txn_type VARCHAR(30), txn_qbo_id VARCHAR(20), line_num INT,
  txn_date DATE NOT NULL,
  account_key INT NOT NULL REFERENCES dim_account,
  customer_key INT REFERENCES dim_customer,
  vendor_key INT REFERENCES dim_vendor,
  class_key INT REFERENCES dim_class,
  amount_signed DECIMAL(15,2) NOT NULL,
  memo VARCHAR(500),
  is_voided BOOLEAN DEFAULT FALSE, is_deleted BOOLEAN DEFAULT FALSE,
  source_sync_at TIMESTAMP,
  UNIQUE (txn_type, txn_qbo_id, line_num)
);
CREATE TABLE fact_budget (
  budget_month DATE, account_key INT REFERENCES dim_account,
  class_key INT NULL, amount DECIMAL(15,2),
  PRIMARY KEY (budget_month, account_key, class_key)
);
CREATE TABLE sync_state (
  entity_type VARCHAR(30) PRIMARY KEY, watermark TIMESTAMP,
  last_status VARCHAR(20), last_run TIMESTAMP, rows_upserted INT
);
CREATE TABLE qa_reports_snapshot (
  report VARCHAR(40), period_month DATE, section VARCHAR(40),
  amount DECIMAL(15,2), captured_at TIMESTAMP
);
```

### 2.4 Serve layer
Create views `vw_fact_gl`, `vw_dim_account`, `vw_dim_date`, `vw_dim_class`, `vw_fact_budget` (filter `is_voided=FALSE AND is_deleted=FALSE` in vw_fact_gl). **Power BI connects to views only.**

---

## 3. TRANSFORM RULES (the correctness-critical logic)

### 3.1 Line explosion — switch on `Line[].DetailType`
| DetailType | Source entities | account resolution |
|---|---|---|
| `SalesItemLineDetail` | Invoice, SalesReceipt, CreditMemo | `ItemRef` → Item.IncomeAccountRef |
| `AccountBasedExpenseLineDetail` | Bill, Purchase | `AccountRef` directly |
| `ItemBasedExpenseLineDetail` | Bill, Purchase | `ItemRef` → Item.ExpenseAccountRef |
| `JournalEntryLineDetail` | JournalEntry | `AccountRef` + `PostingType` (Debit/Credit) |
| `DiscountLineDetail` | sales docs | discount account (contra-revenue) |
| skip: `SubTotalLineDetail`, `DescriptionOnly` | — | non-posting |
**Write one unit test per DetailType using captured sandbox JSON fixtures.**

### 3.2 Sign normalization (invariant)
Store `amount_signed` such that: Revenue rows positive when earning; Expense rows positive when spending; P&L math = Revenue − COGS − OpEx + OtherInc − OtherExp − Tax.
Rule: for credit-natural accounts (classification Revenue/Liability/Equity): credit amounts → positive. For debit-natural (Expense/Asset): debit amounts → positive. CreditMemo/RefundReceipt lines flip sign vs Invoice. JE lines use PostingType.

### 3.3 CoA auto-mapping seed (consultant refines afterward)
`account_type` → stmt_section defaults: Income→Revenue · Cost of Goods Sold→COGS · Expense→OpEx · Other Income→OtherInc · Other Expense→OtherExp. Any account with GL activity and NULL stmt_section → raise in validation (§5.2).

---

## 4. PHASED BUILD PLAN

### Phase 0 — Sample data (parallel tracks)
- **Track A (day 1):** manual — create Intuit dev account, sandbox company (QBO Plus, US). Explore via API Explorer. Capture JSON fixtures for every entity + every DetailType into `/fixtures`.
- **Track C (days 1–2):** `generate_synthetic.py` → CSVs matching §2 staging shapes, 24 months, ~2,500 txns, storylines: Q4-heavy seasonality; gross margin −3pp drift in year 2; Marketing overspends budget from month 15; stable Rent/Software; monthly payroll JE. Deterministic seed. Output `/demo_data/*.csv` + loader script.
- **Track B (days 4–7):** `seed_sandbox.py` — POST the same generated transactions into the sandbox via API (Item/Customer/Vendor/Account creation first, then Invoices/Bills/Purchases/JEs). Idempotent (check-before-create by DocNumber). Throttle ≤5 req/s.

### Phase 1 — Extractor
CLI `qbo_sync` with commands: `auth` (OAuth flow + token vault), `backfill [entity...]`, `cdc`, `status`. Config via env/.env: CLIENT_ID, CLIENT_SECRET, REALM_ID, DB_URL, ENV=sandbox|prod. Structured logging to `sync_state` + stdout JSON lines.
**Gate P1:** backfill of seeded sandbox completes; row counts in raw_* match `SELECT COUNT(*)` per entity via API; a CDC run after editing one sandbox invoice upserts exactly that invoice; killing an invoice in UI marks is_deleted.

### Phase 2 — Transforms
Implement §3 as SQL (or dbt models): raw → stg_* → fact_gl + dims. Deterministic, re-runnable (full-refresh safe + incremental upsert path).
**Gate P2:** unit tests per DetailType pass; fact_gl has zero orphan account_keys; re-running transforms twice yields identical row counts.

### Phase 3 — Validation suite
- V1: parse Reports API ProfitAndLoss (monthly, accrual) into qa_reports_snapshot; compare per month × stmt_section vs fact_gl aggregates. **Tolerance $0.01. Fail loudly.**
- V2: unmapped-account report. V3: orphan/dead-letter report.
**Gate P3:** 24/24 months reconcile on seeded sandbox.

### Phase 4 — Power BI template
Build per §6 layout + §7 DAX. Data source = §2.4 views via parameters (Server, Database, FY_START). Save as .pbit + a .pbix bound to demo CSVs.
**Gate P4:** Definition-of-done checklist §8 all checked.

---

## 5. VALIDATION QUERIES (implement verbatim intent)
```sql
-- V1 reconciliation core
SELECT d.year_month, a.stmt_section, SUM(g.amount_signed) AS etl_amount
FROM vw_fact_gl g JOIN vw_dim_account a USING/ON (account_key)
JOIN vw_dim_date d ON d.d = g.txn_date
GROUP BY 1,2
-- diff against qa_reports_snapshot; assert ABS(diff) <= 0.01
-- V2 unmapped
SELECT a.qbo_id, a.account_name FROM dim_account a
WHERE a.stmt_section IS NULL
  AND EXISTS (SELECT 1 FROM fact_gl g WHERE g.account_key = a.account_key);
```

---

## 6. POWER BI LAYOUT SPEC (single page, 16:9 1280×720)

```
Header 48px: title + slicers [FY ▾][Month|QTD|YTD toggle][vs PY|vs Budget toggle]
KPI band 110px, 4 cards: Revenue · Gross Profit (w/ GP%) · OpEx · Net Income (w/ NI% + sparkline)
   each card: value + delta vs comparison, semantic arrow
HERO (≈55% canvas): P&L Matrix
   rows: stmt_section → stmt_group → account_name (ordered by stmt_sort;
         computed rows GROSS PROFIT / EBITDA / NET INCOME via pnl_layout
         disconnected table + SWITCH measure)
   cols: Actual | ΔPY data-bar | ΔPY% | Budget | ΔBud data-bar | 12m sparkline
   collapse-all default; drill-through per row → Transaction Detail page;
   row tooltip: 12-month mini chart
Bottom 200px, two visuals:
   left: Waterfall Revenue→−COGS→−OpEx→±Other→Net Income (follows slicers)
   right: NI by month, 24 cols; PY as grey outline cols; Budget dotted line
```
**Design tokens:** Segoe UI; numbers right-aligned $K 0–1dp, tabular figures. Ink #1F2733 on white; positive #188038 / negative #C5221F ONLY on variance elements; reference series grey #9AA4AF (PY solid, Budget dotted — consistent everywhere); no vertical gridlines, no backgrounds, identical scales across comparable charts. Expenses displayed positive; variance logic inverted for expense rows (over budget = bad = red).

---

## 7. DAX MEASURE PACK (create exactly; refine names to house style)
```dax
Amount       := SUM ( vw_fact_gl[amount_signed] )
Revenue      := CALCULATE ( [Amount], vw_dim_account[stmt_section] = "Revenue" )
COGS         := CALCULATE ( [Amount], vw_dim_account[stmt_section] = "COGS" )
Gross Profit := [Revenue] - [COGS]
GP %         := DIVIDE ( [Gross Profit], [Revenue] )
OpEx         := CALCULATE ( [Amount], vw_dim_account[stmt_section] = "OpEx" )
EBITDA       := [Gross Profit] - [OpEx]
Other Net    := CALCULATE([Amount], vw_dim_account[stmt_section]="OtherInc")
              - CALCULATE([Amount], vw_dim_account[stmt_section] IN {"OtherExp","Tax"})
Net Income   := [Gross Profit] - [OpEx] + [Other Net]
NI %         := DIVIDE ( [Net Income], [Revenue] )
Amount PY    := CALCULATE ( [Amount], SAMEPERIODLASTYEAR ( vw_dim_date[d] ) )
Δ PY         := [Amount] - [Amount PY]
Δ PY %       := DIVIDE ( [Δ PY], ABS ( [Amount PY] ) )
Budget       := SUM ( vw_fact_budget[amount] )
Δ Budget     := [Amount] - [Budget]
Δ Budget %   := DIVIDE ( [Δ Budget], ABS ( [Budget] ) )
-- expense-aware "good/bad" for conditional formatting:
Var Sentiment := VAR s = SELECTEDVALUE(vw_dim_account[stmt_section])
  RETURN IF ( s IN {"COGS","OpEx","OtherExp","Tax"}, -[Δ Budget], [Δ Budget] )
Amount YTD   := TOTALYTD ( [Amount], vw_dim_date[d], "..FY_END.." )
```
Model: star, single-direction; dim_date marked as date table; relationships dim_*[key] 1→* fact tables. Field parameters: Period (Month/QTD/YTD), Comparison (PY/Budget).

---

## 8. DEFINITION OF DONE (v1 release gate)
- [ ] Matrix totals match QBO ProfitAndLoss to $0.01 (attach side-by-side screenshot)
- [ ] FY_START is a parameter; tested with FY_START=1 and 7
- [ ] Collapse-all default fits one screen, no scroll
- [ ] All currency $K 0–1dp; all % 1dp; tabular alignment verified
- [ ] Drill-through + row tooltips functional
- [ ] .pbit opens clean against empty warehouse (no cached data); .pbix demo opens offline on CSVs
- [ ] Refresh < 2 min @ 3K transactions
- [ ] All Phase gates P1–P3 green in CI (pytest + SQL tests)

## 9. GUARDRAILS FOR THE AI ASSISTANT
1. Never store tokens in code, logs, or fixtures — env/vault only; scrub fixtures of realmIds.
2. Never call production QBO endpoints in tests; sandbox/fixtures only.
3. Amounts are DECIMAL end-to-end; reject any float conversion in review.
4. Do not "fix" reconciliation failures by adjusting tolerances — find the sign/mapping bug.
5. Do not add features outside §0 scope without explicit instruction.
6. Prefer warehouse SQL over Power Query for any transform logic.
7. When QBO docs conflict with this spec (limits, minorversion), flag it — Intuit's platform changes frequently; do not silently adapt.
