# Star schema — QBO PnL semantic model

> Model: `PNL/QBO PnL.SemanticModel` (TMDL, compatibility level 1600, Import mode). Source: the five serve views
> in schema `qbo` (spec 2.4), read as role `qbo_reader`. The model reads **serve views only**.
> Owner: PBI lane (bip). Keep in lockstep with the TMDL.

```
                    DimDate (date table, key d)
                      date_key 1
                     /          \
                    *            *
   DimAccount 1 -* FactGL       FactBudget *- 1 DimAccount
   DimClass   1 -* FactGL       FactBudget *- 1 DimClass

   Disconnected: pnl_layout · Period · Comparison · WaterfallStep · _Measures
```

## Tables

| Model table | Source | Role | Grain | Key |
|---|---|---|---|---|
| `FactGL` | `qbo.vw_fact_gl` | fact | one posted GL line (Revenue / Expense classification; voided + deleted removed) | `gl_key` (hidden) |
| `FactBudget` | `qbo.vw_fact_budget` | fact | budget month × account × class | `budget_key` (hidden) |
| `DimAccount` | `qbo.vw_dim_account` | dimension | QBO account + consultant mapping (`stmt_section`, `stmt_group`, `stmt_sort`) | `account_key` |
| `DimDate` | `qbo.vw_dim_date` | dimension, **marked date table** on `d` (`dataCategory: Time`, `d` = key) | day, contiguous whole calendar years | `date_key` (yyyymmdd) |
| `DimClass` | `qbo.vw_dim_class` | dimension | QBO class | `class_key` |
| `pnl_layout` | DAX `DATATABLE` | disconnected | 9 statement rows: Revenue, COGS, GROSS PROFIT, OpEx, EBITDA, Other income, Other expense, Tax, NET INCOME | `row_key` |
| `Period` | DAX `DATATABLE` | disconnected selector | Month / QTD / YTD | — |
| `Comparison` | DAX `DATATABLE` | disconnected selector | PY / Budget | — |
| `WaterfallStep` | DAX `DATATABLE` | disconnected categories | Revenue / − COGS / − OpEx / ± Other | `step_key` |
| `_Measures` | DAX `ROW` | measure table | all 67 measures (`measure-dictionary.md`) | — |

Model table names follow the house style (`Dim*` / `Fact*`). Column names are kept **exactly as in the views**
(snake_case) so the view contract stays readable 1:1. That differs from the PascalCase column rule in the project instructions
Track C. Renaming is a Desktop job (it fixes the visual references), not a hand edit.

## Relationships (all single direction, many → one, active)

| From (many) | To (one) |
|---|---|
| `FactGL[date_key]` | `DimDate[date_key]` |
| `FactGL[account_key]` | `DimAccount[account_key]` |
| `FactGL[class_key]` | `DimClass[class_key]` |
| `FactBudget[date_key]` (first day of budget month) | `DimDate[date_key]` |
| `FactBudget[account_key]` | `DimAccount[account_key]` |
| `FactBudget[class_key]` | `DimClass[class_key]` |

`class_key` is blank on unclassed lines. They fall into DimClass's blank member, which is expected.
`customer_key` / `vendor_key` are loaded (hidden) but have no dimension: `vw_dim_customer` / `vw_dim_vendor`
are not in the spec 2.4 serve layer.

## Columns and types

- Keys are all hidden, `int64`.
- Money (`amount_signed`, `amount`) is `numeric(15,2)` → Power Query `Currency.Type` → model **`decimal`** (fixed
  decimal), never double. The type step folds into the PostgreSQL query.
- Postgres `date` → `dateTime` with the `UnderlyingDateTimeDataType = Date` annotation, format `yyyy-mm-dd`.
- `summarizeBy: none` everywhere and `discourageImplicitMeasures` is on, so every number comes from a measure.
- Auto date/time is off (`__PBI_TimeIntelligenceEnabled = 0`). `DimDate` is the only calendar.

## Power Query notes

- Every fact and dimension query is `PostgreSQL.Database(Server, Database)` → `{[Schema = "qbo", Item = "vw_*"]}`.
  They fold completely, except for `DimDate`.
- **DimDate fiscal columns come from the `FY_START` parameter.** The view's `fiscal_year` / `fiscal_period` (built
  from the dbt var `fy_start`) are removed and rebuilt in M with the dbt rule: a fiscal year is named by the
  calendar year it ends in, and `fiscal_period = mod(m − FY_START + 12, 12) + 1`. This breaks folding for
  DimDate on purpose (a few thousand rows). It makes the PBI parameter the runtime source of truth (project instructions:
  "Power BI parameters … are the canonical source of truth at runtime"), so FY_START 1 and 7 can be tested
  without re-running dbt. *ADR-worthy: confirm, or move the fiscal logic back to the view only.*
- `DimDate[month_name]` sorts by `fiscal_period`, so months list in fiscal order (Jul first when FY_START = 7).

## Matrix row mechanics (pnl_layout)

The matrix rows are `pnl_layout[row_label]` → `DimAccount[stmt_group]` → `DimAccount[account_name]`.
`[PnL Row]` reads `pnl_layout[row_key]`:

- **section rows** (Revenue, COGS, OpEx, OtherInc, OtherExp, Tax): `CALCULATE ( [Amount], DimAccount[stmt_section] = row_key )`.
  Account groups from other sections evaluate to blank and are hidden, so each section expands only into its
  own groups and accounts.
- **total rows** (GP, EBITDA, NI): the spec measures. They are blank under any account group, so total rows do
  not expand.
- **grand total**: blank. A blank "Total" row stays in the matrix (see refresh.md, "finish in Desktop").
