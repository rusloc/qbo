# Measure dictionary — QBO PnL

> Generated from `PNL/QBO PnL.SemanticModel/definition/tables/_Measures.tmdl` (67 measures, all in
> the `_Measures` table). Owner: PBI lane (bip). Regenerate after every measure change; this file and the
> TMDL must stay in lockstep (project instructions, Track C).

## Sign convention (read first)

`FactGL[amount_signed]` and `FactBudget[amount]` arrive from the warehouse already in **P&L presentation
sign** (spec 3.2, `stg_txn_line.sql`): credit-natural accounts (Revenue) are positive on credit, debit-natural
accounts (Expense) positive on debit. So **every section is positive in its natural direction**: revenue
earned > 0, COGS / OpEx / other expense / tax spent > 0. Consequences:

- Section measures are plain `SUM`s filtered by `DimAccount[stmt_section]`. **Expenses display positive** (spec 6)
  with no sign flip in DAX.
- Totals apply the statement arithmetic: Gross Profit = Revenue − COGS; EBITDA = GP − OpEx;
  Net Income = GP − OpEx + (OtherInc − OtherExp − Tax).
- A refund / credit memo lowers its section (negative amounts are possible on a line, not the norm on a section).
- Variance colour is **inverted for expense rows** (`pnl_layout[is_expense]`): cost above PY / budget = red.
  The arrow in KPI labels shows direction only; the colour shows good / bad.
- Accounts with a blank `stmt_section` (unmapped) are in `[Amount]` but in **no** P&L line and not in Net Income.
  V2 (unmapped accounts) must be clean before totals reconcile with QBO.

## Period window (Month | QTD | YTD) and FY_START

The spec's `TOTALYTD ( ..., "..FY_END.." )` needs a literal year-end and cannot follow the `FY_START`
parameter. Instead every windowed measure filters the **fiscal columns** of `DimDate` (which Power Query rebuilds
from `FY_START`): fiscal year `[Selected FY]`, fiscal periods `[Period Start]`..`[As-of Period]`.
PY = the same periods of `[Selected FY] − 1`, so PY follows fiscal years for any FY_START.

- `[Selected FY]`: FY slicer value; no selection → fiscal year of the latest posted transaction.
- `[As-of Period]`: Month slicer value; no selection → last fiscal period with posted transactions in that FY.
- `[Period Mode]`: Period slicer; no selection → **YTD**. `[Comparison Mode]`: no selection → **PY**.
- QTD = fiscal quarter of the as-of period (periods 1–3, 4–6, …).

## Measures by folder

### Base

| Measure | Format | Meaning |
|---|---|---|
| Amount | $K, 1 dp | Sum of FactGL[amount_signed]. Every P&L section is positive in its natural direction (revenue earned, cost spent). |
| Budget | $K, 1 dp | Sum of FactBudget[amount], same sign convention as Amount. |

### P&L

| Measure | Format | Meaning |
|---|---|---|
| Revenue | $K, 1 dp | Amount on accounts mapped to stmt_section Revenue. |
| COGS | $K, 1 dp | Amount on COGS accounts, positive when spent. |
| Gross Profit | $K, 1 dp | — |
| GP % | %, 1 dp | — |
| OpEx | $K, 1 dp | Amount on OpEx accounts, positive when spent. |
| EBITDA | $K, 1 dp | — |
| Other Net | $K, 1 dp | Other income minus other expense and tax. |
| Net Income | $K, 1 dp | Revenue - COGS - OpEx + OtherInc - OtherExp - Tax (spec 3.2). Accounts with a blank stmt_section are not in Net Income (V2 must be clean). |
| NI % | %, 1 dp | — |

### Comparison

| Measure | Format | Meaning |
|---|---|---|
| Amount PY | $K, 1 dp | Amount in the same dates one year earlier (spec 7). |
| Δ PY | $K, 1 dp, signed | — |
| Δ PY % | %, 1 dp, signed | — |
| Δ Budget | $K, 1 dp, signed | — |
| Δ Budget % | %, 1 dp, signed | — |
| Var Sentiment | $K, 1 dp, signed | Expense-aware budget variance: positive = good. Expense sections invert the sign (over budget = bad). |
| Amount YTD | $K, 1 dp | Fiscal year-to-date Amount through the last fiscal period in context. Replaces the spec TOTALYTD, which needs a literal year-end date and cannot follow the FY_START parameter. |

### P&L\Budget

| Measure | Format | Meaning |
|---|---|---|
| Revenue Budget | $K, 1 dp | — |
| COGS Budget | $K, 1 dp | — |
| Gross Profit Budget | $K, 1 dp | — |
| OpEx Budget | $K, 1 dp | — |
| EBITDA Budget | $K, 1 dp | — |
| Other Net Budget | $K, 1 dp | — |
| Net Income Budget | $K, 1 dp | — |

### Selection

| Measure | Format | Meaning |
|---|---|---|
| Selected FY | integer | Fiscal year on the FY slicer; with no selection, the fiscal year of the latest posted transaction. |
| As-of Period | integer | Fiscal period the Month / QTD / YTD window ends in: the month picked on the Month slicer, else the last period with posted transactions in the selected fiscal year. |
| Period Mode | text | Month \| QTD \| YTD; YTD when nothing is selected. |
| Comparison Mode | text | PY \| Budget; PY when nothing is selected. |
| Period Start | integer | First fiscal period of the selected window. |
| Header Context | text | Dynamic matrix title, e.g. "P&L \| FY2026 \| YTD through March". |

### Matrix\Rows

| Measure | Format | Meaning |
|---|---|---|
| PnL Row | $K, 1 dp | Actual value of the current pnl_layout row in the current filter context. Total rows show only at statement level, never under an account group. |
| PnL Row Budget | $K, 1 dp | Budget value of the current pnl_layout row. |

### Matrix

| Measure | Format | Meaning |
|---|---|---|
| PnL Actual | $K, 1 dp | Row actual over the selected window: fiscal periods [Period Start]..[As-of Period] of [Selected FY]. |
| PnL PY | $K, 1 dp | Same window, previous fiscal year. |
| PnL Budget | $K, 1 dp | Row budget over the selected window. |
| PnL Δ PY | $K, 1 dp, signed | — |
| PnL Δ PY % | %, 1 dp, signed | — |
| PnL Δ Budget | $K, 1 dp, signed | — |
| PnL Δ Budget % | %, 1 dp, signed | — |
| PnL Cmp | $K, 1 dp | PY or Budget for the row, per the Comparison slicer. |
| PnL Δ Cmp | $K, 1 dp, signed | — |

### Matrix\Formatting

| Measure | Format | Meaning |
|---|---|---|
| PnL Δ PY Color | text | Font colour for Δ PY: green good / red bad; expense rows inverted (cost up = red). |
| PnL Δ Budget Color | text | Font colour for Δ Budget: green good / red bad; expense rows inverted (over budget = red). |
| PnL Δ Cmp Color | text | Colour for the KPI delta vs the selected comparison; expense rows inverted. |
| PnL Δ Label | text | KPI subtitle text: arrow, delta in $K and % vs the selected comparison. |

### KPI

| Measure | Format | Meaning |
|---|---|---|
| Revenue (Period) | $K, 1 dp | — |
| COGS (Period) | $K, 1 dp | — |
| Gross Profit (Period) | $K, 1 dp | — |
| OpEx (Period) | $K, 1 dp | — |
| EBITDA (Period) | $K, 1 dp | — |
| Net Income (Period) | $K, 1 dp | — |
| Other Net (Period) | $K, 1 dp | Other income - other expense - tax over the window (= Net Income - EBITDA). |
| GP % (Period) | %, 1 dp | — |
| NI % (Period) | %, 1 dp | — |

### KPI\Labels

| Measure | Format | Meaning |
|---|---|---|
| Revenue Δ Label | text | — |
| Gross Profit Δ Label | text | — |
| OpEx Δ Label | text | — |
| Net Income Δ Label | text | — |
| Revenue Δ Color | text | — |
| Gross Profit Δ Color | text | — |
| OpEx Δ Color | text | — |
| Net Income Δ Color | text | — |

### Charts

| Measure | Format | Meaning |
|---|---|---|
| Waterfall Value | $K, 1 dp, signed | Net income bridge over the selected window: Revenue, -COGS, -OpEx, +/-Other; total = Net Income. |
| NI Month | $K, 1 dp | Net Income per month of the selected fiscal year (ignores Period / Month selection). |
| NI Month PY | $K, 1 dp | Net Income in the same fiscal month of the previous fiscal year. |
| NI Month Budget | $K, 1 dp | Budgeted Net Income per month of the selected fiscal year. |

## DAX

### Base

#### Amount

```dax
Amount =
SUM ( FactGL[amount_signed] )
```

#### Budget

```dax
Budget =
SUM ( FactBudget[amount] )
```

### P&L

#### Revenue

```dax
Revenue =
CALCULATE (
    [Amount]
    ,DimAccount[stmt_section] = "Revenue"
)
```

#### COGS

```dax
COGS =
CALCULATE (
    [Amount]
    ,DimAccount[stmt_section] = "COGS"
)
```

#### Gross Profit

```dax
Gross Profit =
[Revenue] - [COGS]
```

#### GP %

```dax
GP % =
DIVIDE ( [Gross Profit], [Revenue] )
```

#### OpEx

```dax
OpEx =
CALCULATE (
    [Amount]
    ,DimAccount[stmt_section] = "OpEx"
)
```

#### EBITDA

```dax
EBITDA =
[Gross Profit] - [OpEx]
```

#### Other Net

```dax
Other Net =
VAR _other_income   =
    CALCULATE (
        [Amount]
        ,DimAccount[stmt_section] = "OtherInc"
    )
VAR _other_expense  =
    CALCULATE (
        [Amount]
        ,DimAccount[stmt_section] IN { "OtherExp", "Tax" }
    )
RETURN
    _other_income - _other_expense
```

#### Net Income

```dax
Net Income =
[Gross Profit] - [OpEx] + [Other Net]
```

#### NI %

```dax
NI % =
DIVIDE ( [Net Income], [Revenue] )
```

### Comparison

#### Amount PY

```dax
Amount PY =
CALCULATE (
    [Amount]
    ,SAMEPERIODLASTYEAR ( DimDate[d] )
)
```

#### Δ PY

```dax
Δ PY =
[Amount] - [Amount PY]
```

#### Δ PY %

```dax
Δ PY % =
DIVIDE ( [Δ PY], ABS ( [Amount PY] ) )
```

#### Δ Budget

```dax
Δ Budget =
[Amount] - [Budget]
```

#### Δ Budget %

```dax
Δ Budget % =
DIVIDE ( [Δ Budget], ABS ( [Budget] ) )
```

#### Var Sentiment

```dax
Var Sentiment =
VAR _section       = SELECTEDVALUE ( DimAccount[stmt_section] )
VAR _result        =
    IF (
        _section IN { "COGS", "OpEx", "OtherExp", "Tax" }
        ,-[Δ Budget]
        ,[Δ Budget]
    )
RETURN
    _result
```

#### Amount YTD

```dax
Amount YTD =
VAR _fy            = MAX ( DimDate[fiscal_year] )
VAR _to            = MAX ( DimDate[fiscal_period] )
VAR _result        =
    CALCULATE (
        [Amount]
        ,REMOVEFILTERS ( DimDate )
        ,DimDate[fiscal_year] = _fy
        ,DimDate[fiscal_period] <= _to
    )
RETURN
    _result
```

### P&L\Budget

#### Revenue Budget

```dax
Revenue Budget =
CALCULATE (
    [Budget]
    ,DimAccount[stmt_section] = "Revenue"
)
```

#### COGS Budget

```dax
COGS Budget =
CALCULATE (
    [Budget]
    ,DimAccount[stmt_section] = "COGS"
)
```

#### Gross Profit Budget

```dax
Gross Profit Budget =
[Revenue Budget] - [COGS Budget]
```

#### OpEx Budget

```dax
OpEx Budget =
CALCULATE (
    [Budget]
    ,DimAccount[stmt_section] = "OpEx"
)
```

#### EBITDA Budget

```dax
EBITDA Budget =
[Gross Profit Budget] - [OpEx Budget]
```

#### Other Net Budget

```dax
Other Net Budget =
VAR _other_income   =
    CALCULATE (
        [Budget]
        ,DimAccount[stmt_section] = "OtherInc"
    )
VAR _other_expense  =
    CALCULATE (
        [Budget]
        ,DimAccount[stmt_section] IN { "OtherExp", "Tax" }
    )
RETURN
    _other_income - _other_expense
```

#### Net Income Budget

```dax
Net Income Budget =
[Gross Profit Budget] - [OpEx Budget] + [Other Net Budget]
```

### Selection

#### Selected FY

```dax
Selected FY =
VAR _last_date     =
    CALCULATE (
        MAX ( FactGL[txn_date] )
        ,REMOVEFILTERS ( DimDate )
        ,REMOVEFILTERS ( DimAccount )
    )
VAR _latest_fy     =
    CALCULATE (
        MAX ( DimDate[fiscal_year] )
        ,REMOVEFILTERS ( DimDate )
        ,DimDate[d] = _last_date
    )
VAR _result        =
    IF (
        ISFILTERED ( DimDate[fiscal_year] )
        ,MAX ( DimDate[fiscal_year] )
        ,COALESCE ( _latest_fy, MAX ( DimDate[fiscal_year] ) )
    )
RETURN
    _result
```

#### As-of Period

```dax
As-of Period =
VAR _fy            = [Selected FY]
VAR _picked        =
    IF (
        ISFILTERED ( DimDate[month_name] )
        ,MAX ( DimDate[fiscal_period] )
    )
VAR _last_date     =
    CALCULATE (
        MAX ( FactGL[txn_date] )
        ,REMOVEFILTERS ( DimDate )
        ,REMOVEFILTERS ( DimAccount )
        ,DimDate[fiscal_year] = _fy
    )
VAR _last_period   =
    CALCULATE (
        MAX ( DimDate[fiscal_period] )
        ,REMOVEFILTERS ( DimDate )
        ,DimDate[d] = _last_date
    )
VAR _result        = COALESCE ( _picked, _last_period, 12 )
RETURN
    _result
```

#### Period Mode

```dax
Period Mode =
SELECTEDVALUE ( Period[Period], "YTD" )
```

#### Comparison Mode

```dax
Comparison Mode =
SELECTEDVALUE ( Comparison[Comparison], "PY" )
```

#### Period Start

```dax
Period Start =
VAR _to            = [As-of Period]
VAR _mode          = [Period Mode]
VAR _result        =
    SWITCH (
        _mode
        ,"Month"
            ,_to
        ,"QTD"
            ,INT ( ( _to - 1 ) / 3 ) * 3 + 1
        ,1
    )
RETURN
    _result
```

#### Header Context

```dax
Header Context =
VAR _fy            = [Selected FY]
VAR _to            = [As-of Period]
VAR _mode          = [Period Mode]
VAR _month         =
    CALCULATE (
        SELECTEDVALUE ( DimDate[month_name] )
        ,REMOVEFILTERS ( DimDate )
        ,DimDate[fiscal_year] = _fy
        ,DimDate[fiscal_period] = _to
    )
VAR _window        =
    SWITCH (
        _mode
        ,"Month"
            ,_month
        ,_mode & " through " & _month
    )
VAR _result        = "P&L  |  FY" & _fy & "  |  " & _window
RETURN
    _result
```

### Matrix\Rows

#### PnL Row

```dax
PnL Row =
VAR _key           = SELECTEDVALUE ( pnl_layout[row_key] )
VAR _is_total      = SELECTEDVALUE ( pnl_layout[is_total] )
VAR _result        =
    SWITCH (
        TRUE ()
        ,ISBLANK ( _key )
            ,BLANK ()
        ,_is_total && ISINSCOPE ( DimAccount[stmt_group] )
            ,BLANK ()
        ,_key = "GP"
            ,[Gross Profit]
        ,_key = "EBITDA"
            ,[EBITDA]
        ,_key = "NI"
            ,[Net Income]
        ,CALCULATE (
            [Amount]
            ,DimAccount[stmt_section] = _key
        )
    )
RETURN
    _result
```

#### PnL Row Budget

```dax
PnL Row Budget =
VAR _key           = SELECTEDVALUE ( pnl_layout[row_key] )
VAR _is_total      = SELECTEDVALUE ( pnl_layout[is_total] )
VAR _result        =
    SWITCH (
        TRUE ()
        ,ISBLANK ( _key )
            ,BLANK ()
        ,_is_total && ISINSCOPE ( DimAccount[stmt_group] )
            ,BLANK ()
        ,_key = "GP"
            ,[Gross Profit Budget]
        ,_key = "EBITDA"
            ,[EBITDA Budget]
        ,_key = "NI"
            ,[Net Income Budget]
        ,CALCULATE (
            [Budget]
            ,DimAccount[stmt_section] = _key
        )
    )
RETURN
    _result
```

### Matrix

#### PnL Actual

```dax
PnL Actual =
VAR _fy            = [Selected FY]
VAR _from          = [Period Start]
VAR _to            = [As-of Period]
VAR _result        =
    CALCULATE (
        [PnL Row]
        ,REMOVEFILTERS ( DimDate )
        ,DimDate[fiscal_year] = _fy
        ,DimDate[fiscal_period] >= _from
        ,DimDate[fiscal_period] <= _to
    )
RETURN
    _result
```

#### PnL PY

```dax
PnL PY =
VAR _fy            = [Selected FY]
VAR _from          = [Period Start]
VAR _to            = [As-of Period]
VAR _result        =
    CALCULATE (
        [PnL Row]
        ,REMOVEFILTERS ( DimDate )
        ,DimDate[fiscal_year] = _fy - 1
        ,DimDate[fiscal_period] >= _from
        ,DimDate[fiscal_period] <= _to
    )
RETURN
    _result
```

#### PnL Budget

```dax
PnL Budget =
VAR _fy            = [Selected FY]
VAR _from          = [Period Start]
VAR _to            = [As-of Period]
VAR _result        =
    CALCULATE (
        [PnL Row Budget]
        ,REMOVEFILTERS ( DimDate )
        ,DimDate[fiscal_year] = _fy
        ,DimDate[fiscal_period] >= _from
        ,DimDate[fiscal_period] <= _to
    )
RETURN
    _result
```

#### PnL Δ PY

```dax
PnL Δ PY =
[PnL Actual] - [PnL PY]
```

#### PnL Δ PY %

```dax
PnL Δ PY % =
DIVIDE ( [PnL Δ PY], ABS ( [PnL PY] ) )
```

#### PnL Δ Budget

```dax
PnL Δ Budget =
[PnL Actual] - [PnL Budget]
```

#### PnL Δ Budget %

```dax
PnL Δ Budget % =
DIVIDE ( [PnL Δ Budget], ABS ( [PnL Budget] ) )
```

#### PnL Cmp

```dax
PnL Cmp =
VAR _mode          = [Comparison Mode]
VAR _result        =
    IF (
        _mode = "Budget"
        ,[PnL Budget]
        ,[PnL PY]
    )
RETURN
    _result
```

#### PnL Δ Cmp

```dax
PnL Δ Cmp =
[PnL Actual] - [PnL Cmp]
```

### Matrix\Formatting

#### PnL Δ PY Color

```dax
PnL Δ PY Color =
VAR _delta         = [PnL Δ PY]
VAR _ref           = [PnL PY]
VAR _is_expense    = SELECTEDVALUE ( pnl_layout[is_expense] )
VAR _good          = IF ( _is_expense, -_delta, _delta )
VAR _result        =
    SWITCH (
        TRUE ()
        ,ISBLANK ( _ref ) || ISBLANK ( _delta )
            ,"#9AA4AF"
        ,_good > 0
            ,"#188038"
        ,_good < 0
            ,"#C5221F"
        ,"#1F2733"
    )
RETURN
    _result
```

#### PnL Δ Budget Color

```dax
PnL Δ Budget Color =
VAR _delta         = [PnL Δ Budget]
VAR _ref           = [PnL Budget]
VAR _is_expense    = SELECTEDVALUE ( pnl_layout[is_expense] )
VAR _good          = IF ( _is_expense, -_delta, _delta )
VAR _result        =
    SWITCH (
        TRUE ()
        ,ISBLANK ( _ref ) || ISBLANK ( _delta )
            ,"#9AA4AF"
        ,_good > 0
            ,"#188038"
        ,_good < 0
            ,"#C5221F"
        ,"#1F2733"
    )
RETURN
    _result
```

#### PnL Δ Cmp Color

```dax
PnL Δ Cmp Color =
VAR _delta         = [PnL Δ Cmp]
VAR _ref           = [PnL Cmp]
VAR _is_expense    = SELECTEDVALUE ( pnl_layout[is_expense] )
VAR _good          = IF ( _is_expense, -_delta, _delta )
VAR _result        =
    SWITCH (
        TRUE ()
        ,ISBLANK ( _ref ) || ISBLANK ( _delta )
            ,"#9AA4AF"
        ,_good > 0
            ,"#188038"
        ,_good < 0
            ,"#C5221F"
        ,"#1F2733"
    )
RETURN
    _result
```

#### PnL Δ Label

```dax
PnL Δ Label =
VAR _cmp           = [PnL Cmp]
VAR _delta         = [PnL Δ Cmp]
VAR _mode          = [Comparison Mode]
VAR _pct           = DIVIDE ( _delta, ABS ( _cmp ) )
VAR _arrow         = IF ( _delta >= 0, UNICHAR ( 9650 ), UNICHAR ( 9660 ) )
VAR _result        =
    IF (
        ISBLANK ( _cmp )
        ,"No " & _mode & " data"
        ,_arrow & " " & FORMAT ( _delta / 1000, "+$#,0.0;-$#,0.0" ) & "K  "
            & FORMAT ( _pct, "+0.0%;-0.0%" ) & " vs " & _mode
    )
RETURN
    _result
```

### KPI

#### Revenue (Period)

```dax
Revenue (Period) =
CALCULATE (
    [PnL Actual]
    ,pnl_layout[row_key] = "Revenue"
)
```

#### COGS (Period)

```dax
COGS (Period) =
CALCULATE (
    [PnL Actual]
    ,pnl_layout[row_key] = "COGS"
)
```

#### Gross Profit (Period)

```dax
Gross Profit (Period) =
CALCULATE (
    [PnL Actual]
    ,pnl_layout[row_key] = "GP"
)
```

#### OpEx (Period)

```dax
OpEx (Period) =
CALCULATE (
    [PnL Actual]
    ,pnl_layout[row_key] = "OpEx"
)
```

#### EBITDA (Period)

```dax
EBITDA (Period) =
CALCULATE (
    [PnL Actual]
    ,pnl_layout[row_key] = "EBITDA"
)
```

#### Net Income (Period)

```dax
Net Income (Period) =
CALCULATE (
    [PnL Actual]
    ,pnl_layout[row_key] = "NI"
)
```

#### Other Net (Period)

```dax
Other Net (Period) =
[Net Income (Period)] - [EBITDA (Period)]
```

#### GP % (Period)

```dax
GP % (Period) =
DIVIDE ( [Gross Profit (Period)], [Revenue (Period)] )
```

#### NI % (Period)

```dax
NI % (Period) =
DIVIDE ( [Net Income (Period)], [Revenue (Period)] )
```

### KPI\Labels

#### Revenue Δ Label

```dax
Revenue Δ Label =
CALCULATE (
    [PnL Δ Label]
    ,pnl_layout[row_key] = "Revenue"
)
```

#### Gross Profit Δ Label

```dax
Gross Profit Δ Label =
VAR _delta         =
    CALCULATE (
        [PnL Δ Label]
        ,pnl_layout[row_key] = "GP"
    )
VAR _result        = _delta & "  |  GP% " & FORMAT ( [GP % (Period)], "0.0%" )
RETURN
    _result
```

#### OpEx Δ Label

```dax
OpEx Δ Label =
CALCULATE (
    [PnL Δ Label]
    ,pnl_layout[row_key] = "OpEx"
)
```

#### Net Income Δ Label

```dax
Net Income Δ Label =
VAR _delta         =
    CALCULATE (
        [PnL Δ Label]
        ,pnl_layout[row_key] = "NI"
    )
VAR _result        = _delta & "  |  NI% " & FORMAT ( [NI % (Period)], "0.0%" )
RETURN
    _result
```

#### Revenue Δ Color

```dax
Revenue Δ Color =
CALCULATE (
    [PnL Δ Cmp Color]
    ,pnl_layout[row_key] = "Revenue"
)
```

#### Gross Profit Δ Color

```dax
Gross Profit Δ Color =
CALCULATE (
    [PnL Δ Cmp Color]
    ,pnl_layout[row_key] = "GP"
)
```

#### OpEx Δ Color

```dax
OpEx Δ Color =
CALCULATE (
    [PnL Δ Cmp Color]
    ,pnl_layout[row_key] = "OpEx"
)
```

#### Net Income Δ Color

```dax
Net Income Δ Color =
CALCULATE (
    [PnL Δ Cmp Color]
    ,pnl_layout[row_key] = "NI"
)
```

### Charts

#### Waterfall Value

```dax
Waterfall Value =
VAR _step          = SELECTEDVALUE ( WaterfallStep[step_key] )
VAR _result        =
    SWITCH (
        _step
        ,"Revenue"
            ,[Revenue (Period)]
        ,"COGS"
            ,-[COGS (Period)]
        ,"OpEx"
            ,-[OpEx (Period)]
        ,"Other"
            ,[Other Net (Period)]
        ,[Net Income (Period)]
    )
RETURN
    _result
```

#### NI Month

```dax
NI Month =
VAR _fy            = [Selected FY]
VAR _result        =
    CALCULATE (
        [Net Income]
        ,DimDate[fiscal_year] = _fy
    )
RETURN
    _result
```

#### NI Month PY

```dax
NI Month PY =
VAR _fy            = [Selected FY]
VAR _result        =
    CALCULATE (
        [Net Income]
        ,DimDate[fiscal_year] = _fy - 1
    )
RETURN
    _result
```

#### NI Month Budget

```dax
NI Month Budget =
VAR _fy            = [Selected FY]
VAR _result        =
    CALCULATE (
        [Net Income Budget]
        ,DimDate[fiscal_year] = _fy
    )
RETURN
    _result
```
