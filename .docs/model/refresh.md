# Refresh and connection — QBO PnL

> How the PBIP in `PNL/` connects to the Supabase warehouse and refreshes. No credentials, project refs or
> passwords are stored in the PBIP. They live in the Desktop / Service credential store only.

## Parameters (Transform data → Manage parameters)

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `Server` | Text | `aws-0-eu-west-1.pooler.supabase.com` | Supabase **session pooler** host. Use the pooler, because the direct host is IPv6-only. Use `host:5432` if a port is needed. The default is the region host and carries no project ref. Set it to the client's pooler host. |
| `Database` | Text | `postgres` | Postgres database name. |
| `FY_START` | Number | `1` | First month of the fiscal year (1..12). Rebuilds `DimDate[fiscal_year]` / `[fiscal_period]` on refresh. Any other value fails the DimDate query on purpose. |

## First connection (Desktop)

1. Open `PNL/QBO PnL.pbip`. The banner "Some of the tables have incomplete or no data" is expected until the
   first refresh: the PBIP ships no data cache.
2. Set `Server` (and `FY_START` if the client's fiscal year doesn't start in January). Apply changes.
3. When Desktop asks for credentials for the PostgreSQL source:
   - Authentication: **Database**.
   - User name: **`qbo_reader.<project-ref>`**. The Supabase pooler requires the project ref as a suffix on the
     role name. Take the ref from the client's Supabase dashboard (Connect → Session pooler). Never write it into
     the PBIP or the repo.
   - Password: the `qbo_reader` login password, from the vault. Never commit it.
   - Privacy level: Organizational.
4. Keep **Encrypt connection** on. Supabase requires SSL, and Npgsql in Desktop negotiates it on the pooler.
5. Home → Refresh. Expect 5 Postgres queries (FactGL, FactBudget, DimAccount, DimDate, DimClass). The 4
   disconnected tables are DAX and need no source.

Precondition (Warehouse / dbt lanes): the five `qbo.vw_*` views exist, and `qbo_reader` can log in (it is created
`nologin` in migration `20260925213800`) and has `select` on them. Until then the refresh fails with
"relation does not exist" or an authentication error. That failure is in the warehouse, not the PBIP.

## Checks after a refresh

- `DimDate` marked as date table: Desktop validates that `d` is unique and contiguous. dbt builds whole years,
  so it is.
- Matrix totals reconcile to QBO ProfitAndLoss (accrual) per month × section to $0.01 (spec 8, V1).
- `vw_dim_account` has no P&L account with a blank `stmt_section` (V2). Otherwise Net Income ≠ QBO.
- Refresh time < 2 min at 3K transactions (spec 8). All queries except DimDate fold.
- FY_START tested at 1 and 7 (spec 8): change the parameter, refresh, check that the FY slicer and the YTD
  window move.

## Service (later, ADR-0006)

Publishing, the gateway / cloud connection and the scheduled refresh are not decided yet (ADR-0006). Supabase
is a cloud source, so a cloud connection with the same `qbo_reader.<project-ref>` credentials should work
without a gateway. Verify this when ADR-0006 is written.

## Finish in Desktop (not hand-authored, by design)

These were left out of the PBIP because hand-authoring them risked a project that won't open. Each one is a few
minutes in Desktop. Then save, and commit the PBIP diff.

- Set default slicer selections (FY = latest, Period = YTD, Compare = PY). The measures already default to these
  when nothing is selected.
- Turn off the matrix grand-total row (Format → Row subtotals → per row level → off for "Total"), and check
  where section subtotals sit when a section is expanded.
- Data bars on Δ PY / Δ Budget (spec 6). They are coloured text for now.
- 12-month sparkline column in the matrix, and the NI sparkline on the Net Income card.
- Drill-through page "Transaction Detail" (from a matrix row) and the 12-month row tooltip page.
- Order account groups / accounts by `stmt_sort`. They sort alphabetically today because `stmt_group` and
  `account_name` aren't 1:1 with `stmt_sort`. A group-level sort key from dbt (`stmt_group_sort`) would fix it:
  a request for the ETL + dbt lane.
- Check the combo chart's single shared axis (`secShow = false` should put the Budget line on the column axis),
  and check that the PY columns render as grey outlines.
- Rename model columns to PascalCase if the house rule is enforced (do it in Desktop so visual references follow).
