---
name: dax-sql-formatter
description: >
  House formatting style for SQL AND DAX. Apply this skill to EVERY SQL statement and EVERY DAX
  expression you output — writing new code, refactoring, optimizing, reviewing, or showing example
  snippets — in any SQL dialect (especially PostgreSQL) and in any DAX context (measures, calculated
  columns, calculated tables, visual calculations, TMDL files, Tabular Editor scripts, reportExtensions).
  Trigger whenever the response will contain SQL or DAX: "write a query", "write a measure",
  "refactor this SQL/DAX", "optimize this", "how do I join X and Y", "fix this measure",
  pasted SQL or DAX of any kind, Power BI / semantic model / reporting / analytics questions answered
  with code. Do not wait for the user to ask about formatting — the style applies silently and always,
  unless the user explicitly requests a different style for a specific output.
---

# DAX + SQL Style Formatter

One house style, two languages. The shared goal: code that scans as **vertical blocks** — expressions on the left, names/aliases in a clean right-hand column, filters and arguments stacked one per line, every line independently comment-out-able. Every rule below serves that visual scannability; when in doubt, prefer the option that keeps vertical alignment intact.

Shared DNA across both languages:

| Principle | SQL | DAX |
|---|---|---|
| One item per line | select columns, `and` conditions | VARs, function arguments, filters |
| Leading commas | `,o.total` | `,'Date'[Year] = 2026` |
| `_` prefix for names you invent | column aliases `_revenue` | variables `_revenue` |
| Right-aligned name block | alias block in select | `=` block in VARs |
| Toggle-friendly filters | `where 1=1` + `and` lines | one filter arg per line in `CALCULATE` |
| Stepped branching | `case/when/then` | `SWITCH` / `IF` steps |

---

# Part 1 — SQL

### 1. Keywords: lowercase, always

`select`, `from`, `join`, `on`, `where`, `group by`, `order by`, `case`, `when`, `then`, `else`, `end`, `and`, `or`, `in`, `exists`, `over`, `partition by` — all lowercase. Function names too (`sum`, `coalesce`, `row_number`).

### 2. Select list: leading commas, one column per line

- `select` sits alone on its first line.
- Each column on its own line.
- Continuation lines **start with `,` immediately followed by the column** — no space after the comma.
- The first column line is indented with one extra leading space so all column expressions align vertically with the comma-prefixed lines below.

```sql
select
     o.id
    ,o.created_at
    ,o.total
```

### 3. Every output column gets a custom alias starting with `_`

No bare columns in the select list — even `o.id` becomes `o.id _id`. The alias:
- starts with an underscore: `_order_id`, `_total_amount`
- is written **without `as`**
- is descriptive snake_case

### 4. Aliases form one right-aligned vertical block

Pad with spaces so every alias in a select list starts at the same character position. Pick the position from the longest column expression in that list (+ a small gutter of 2+ spaces). Recalculate per query — don't carry a fixed column number between queries.

```sql
select
     o.id                          _order_id
    ,o.created_at::date            _order_date
    ,c.name                        _customer_name
    ,sum(oi.qty * oi.price)        _total_amount
```

For a multi-line expression (like `case ... end`), the alias goes on the `end` line, padded into the same block.

### 5. Never use `as`

Not for column aliases, not for table aliases. `orders o`, never `orders as o`. Exception: `as` is still required by syntax in places where it's mandatory — CTE definitions (`with t as (...)`) keep their `as`.

### 6. Table aliases: exactly one letter

- First letter of the table name: `orders o`, `customers c`.
- On collision, pick another distinctive letter from the name: `customers c`, `categories g` (from cate**g**ories) — or any unused letter that still hints at the table.
- Applies to CTE references and subqueries in `from`/`join` too.

### 7. `where` always opens with `1=1`

The first line after the table is `where 1=1`. Every real condition goes on its own new line, indented, starting with `and` (or `or`):

```sql
where 1=1
    and o.status = 'paid'
    and o.created_at >= date '2026-01-01'
```

This makes conditions trivially commentable/toggleable — every one of them starts with `and`, so any line can be deleted or commented without breaking the query. Apply the same pattern to `having` when it has multiple conditions (`having 1=1` is not required; just stack `and` lines if there are several).

### 8. `case` / `when` / `then`: stepped indentation

Each level gets its own indent step — `when` indented under `case`, `then` indented under its `when`, `else` at the `when` level, `end` back at the `case` level:

```sql
,case
     when o.status = 'paid'
         then 1
     when o.status = 'refunded'
         then -1
     else 0
 end                           _status_sign
```

The alias rides on the `end` line, aligned into the alias block.

### SQL full example (target output shape)

```sql
with recent_orders as (
    select
         o.id                          _order_id
        ,o.customer_id                 _customer_id
        ,o.created_at::date            _order_date
        ,case
             when o.total >= 1000
                 then 'big'
             when o.total >= 100
                 then 'medium'
             else 'small'
         end                           _order_bucket
        ,o.total                       _total
    from orders o
    where 1=1
        and o.created_at >= date '2026-01-01'
        and o.status = 'paid'
)
select
     c.name                        _customer_name
    ,count(*)                      _orders_cnt
    ,sum(r._total)                 _revenue
    ,max(r._order_date)            _last_order_date
from recent_orders r
join customers c on c.id = r._customer_id
where 1=1
    and c.is_active = true
group by c.name
order by _revenue desc
limit 10;
```

---

# Part 2 — DAX

### 1. Function names and keywords: UPPERCASE, always

`CALCULATE`, `SUMX`, `FILTER`, `DIVIDE`, `VAR`, `RETURN`, `TRUE`, `BLANK`, `IN`, `NOT` — DAX reads as DAX, SQL reads as SQL. Never mix the two conventions.

### 2. References: fully qualified columns, bare measures

- Columns **always** table-qualified: `Sales[Amount]`, `'Order Details'[Qty]` — single quotes only when the table name needs them (spaces/special chars).
- Measures **never** table-qualified: `[Total Sales]`, never `Sales[Total Sales]`. The reader must tell columns from measures at a glance.

### 3. VAR-first bodies, `_` prefix, one step per line

Any measure beyond a one-liner is written as a VAR chain — one logical step per VAR, then a minimal `RETURN`:

- Variable names start with `_`, descriptive snake_case: `_total`, `_prev_year`, `_is_ytd` (mirrors SQL aliases).
- One `VAR` per line; `RETURN` sits alone on its own line at `VAR` level; the returned expression indented below it (or on the same line only when it is a single short name).

### 4. `=` signs form one right-aligned vertical block

Within a VAR chain, pad variable names so all `=` signs align (same rule as the SQL alias block: longest name + 2-space gutter, recalculated per expression):

```dax
VAR _total        = [Total Sales]
VAR _prev         = CALCULATE ( [Total Sales], DATEADD ( 'Date'[Date], -1, YEAR ) )
VAR _growth       = DIVIDE ( _total - _prev, _prev )
RETURN
    _growth
```

A VAR whose expression is multi-line keeps `=` in the block and opens the expression on the next line, indented:

```dax
VAR _filtered     =
    CALCULATE (
        [Total Sales]
        ,'Product'[Category] = "Bikes"
        ,'Date'[Year] = 2026
    )
```

### 5. Multi-line calls: leading commas, one argument per line

When a function call doesn't fit on one line (or takes filter arguments), break it:

- Opening `(` stays on the function line; closing `)` on its own line at the function's indent level.
- First argument on its own line, one indent step in.
- Every further argument starts with `,` immediately followed by the expression — no space after the comma (identical to the SQL select list).

```dax
CALCULATE (
    [Total Sales]
    ,'Date'[Year] = 2026
    ,'Product'[Category] IN { "Bikes", "Accessories" }
    ,KEEPFILTERS ( 'Region'[Country] = "DE" )
)
```

Every filter is one line → any filter can be commented out with `//` without breaking the call (the DAX twin of `where 1=1`). Short calls stay on one line with spaces inside the parens: `DIVIDE ( _num, _den )`, `SUM ( Sales[Amount] )`.

### 6. `SWITCH` / `IF`: stepped indentation

`SWITCH ( TRUE ()` is the DAX `case/when` — same stepped shape: each condition line, its result indented one step below, `ELSE`-value at condition level:

```dax
VAR _bucket       =
    SWITCH (
        TRUE ()
        ,_total >= 1000
            ,"big"
        ,_total >= 100
            ,"medium"
        ,"small"
    )
```

Nested `IF` beyond two levels → rewrite as `SWITCH ( TRUE () ... )`.

### 7. Iterators and table expressions

`SUMX`/`FILTER`/`ADDCOLUMNS` and friends: table argument first line, row expression stacked below with a leading comma; nested table functions indent one step per nesting level:

```dax
VAR _big_orders   =
    SUMX (
        FILTER (
            Sales
            ,Sales[Amount] >= 1000
        )
        ,Sales[Qty] * Sales[Price]
    )
```

### 8. Operators and safety idioms

- Spaces around binary operators: `_a - _b`, `'Date'[Year] = 2026`.
- `DIVIDE ( _num, _den )` instead of `/` whenever the denominator can be zero/blank.
- Comparisons with booleans stay explicit: `Sales[IsReturn] = TRUE ()`.

### DAX full example (target output shape)

```dax
Sales YoY % =
VAR _total        = [Total Sales]
VAR _prev         =
    CALCULATE (
        [Total Sales]
        ,DATEADD ( 'Date'[Date], -1, YEAR )
    )
VAR _growth       = DIVIDE ( _total - _prev, _prev )
VAR _result       =
    SWITCH (
        TRUE ()
        ,ISBLANK ( _prev )
            ,BLANK ()
        ,_growth
    )
RETURN
    _result
```

---

# Scope & Edge Cases

- **Applies to**: any SQL (selects, CTEs, subqueries, views, `insert ... select`, DDL keywords) and any DAX (measures, calculated columns/tables, visual calculations, calculation items, DAX queries with `EVALUATE`, snippets inside TMDL files, Tabular Editor C# string literals, `reportExtensions.json` expressions).
- **DAX inside TMDL**: apply this style to the expression body; TMDL's own rules still win at the file level (tab indentation for the TMDL structure, backtick fencing when the expression contains conflicting characters). Inside a JSON string (visual.json, reportExtensions.json), keep the style but escape per JSON — don't sacrifice correctness for alignment.
- **Visual calculations**: same DAX rules; references use the visual's field names (`[Sum of Sales]`) — treat them like measure references.
- **DDL** (`create table`, `create index`, `alter ...`): lowercase keywords; alias/where rules don't apply.
- **`update`/`delete`**: lowercase keywords + the `where 1=1 and ...` pattern.
- **Tiny inline fragments** in prose (mentioning `where 1=1` or `DIVIDE` itself) don't need the full treatment — only fenced/complete statements do.
- **User-pasted code**: when refactoring or reviewing, return it reformatted to this style, semantics identical. If the paste is a diff-sensitive context (e.g., a one-line TMDL formatString fix), don't reformat surrounding untouched code — surgical diffs beat style completeness.
- **M / Power Query is out of scope** — format M per its own conventions; this skill governs SQL and DAX only.
- **Explicit override**: if the user asks for another style ("uppercase SQL keywords", "trailing commas", "DAX Formatter long style"), follow their request for that output, then return to this style.
