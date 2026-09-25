# TMDL: Measures & Semantic Model Edits

TMDL files live in `<name>.SemanticModel/definition/`. Measures belong to tables → edit `definition/tables/<Table>.tmdl`.

## Syntax fundamentals

- **Tabs for indentation.** Indentation defines object nesting (like YAML). The serializer emits tabs — never convert to spaces.
- Object declaration: `<type> <Name>`, children indented one level.
- Names containing spaces or ` .,;'``{}()[]"` → wrap in single quotes: `measure 'Sales YoY %'`. A literal `'` inside a name is doubled: `'Customer''s Age'`.
- Default property after `=`: for measures that's the DAX expression; multi-line expressions start on the next line, indented deeper than the properties.
- Expressions containing TMDL-conflicting characters (`:` at line start patterns, etc.) are fenced with triple backticks.
- Descriptions: `///` lines directly above the declaration (no blank line between).
- Booleans: bare property name means true (`isHidden`), or explicit `isHidden: false`.
- A property may not be declared twice on one object (parse error).

## Measure anatomy

```tmdl
table Sales
	lineageTag: fa6fb917-28ce-4d34-97ad-9fff4d086e1c

	/// Total invoiced revenue
	measure 'Total Sales' = SUM(Sales[Amount])
		formatString: #,##0.00
		displayFolder: Revenue
		lineageTag: ac99485b-fc61-474e-a30e-d0889efce03f

	/// Year over year growth
	measure 'Sales YoY %' =
			VAR _prev = CALCULATE([Total Sales], DATEADD('Date'[Date], -1, YEAR))
			RETURN
			DIVIDE([Total Sales] - _prev, _prev)
		formatString: +0.0%;-0.0%;0.0%
		displayFolder: Revenue\Growth
		lineageTag: 29fcb593-54b0-4061-ae46-2683f72fe75a

	measure 'Complex' = ```
			// DAX containing characters that would confuse TMDL parsing
			VAR x = "a:b"
			RETURN x
			```
		formatString: 0
		lineageTag: 8e11165d-306e-4e59-b549-fc1cdf4b080f
```

### Measure properties

| Property | Example / values |
|---|---|
| `formatString` | VBA-style: `#,##0`, `#,##0.00`, `0.0%`, `$ #,##0`, `yyyy-MMM-dd`, `#,0,,.0" M"`; sections `pos;neg;zero` |
| `displayFolder` | `Revenue` or nested `Revenue\Growth` (backslash) |
| `lineageTag` | GUID — **preserve on edits; generate a new GUID for new measures** (`python3 -c "import uuid;print(uuid.uuid4())"`) |
| `isHidden` | flag |
| `dataCategory` | e.g. `ImageUrl`, `WebUrl` |
| `detailRowsDefinition` | `detailRowsDefinition = SELECTCOLUMNS(...)` (sub-object with default expression) |
| `formatStringDefinition` | dynamic format string — see below |
| `kpi` | KPI sub-object |
| `annotation` | `annotation PBI_FormatHint = {"isGeneralNumber":true}` |
| `changedProperty` | serializer bookkeeping like `changedProperty = FormatString` — leave existing ones; add `changedProperty = <Prop>` when changing a property on an existing object is optional but harmless |

### Dynamic format strings

```tmdl
	measure 'Smart Value' = [Total Sales]
		formatStringDefinition =
				SWITCH(
				    TRUE(),
				    SELECTEDMEASURE() >= 1e6, "$#,##0,,.0\" M\"",
				    SELECTEDMEASURE() >= 1e3, "$#,##0,.0\" K\"",
				    "$#,##0"
				)
		lineageTag: ...
```
`formatStringDefinition` is a child object with a DAX default expression (mutually exclusive in effect with a static `formatString` — Desktop keeps only one active).

## Common edit operations

**Change a format string** — replace the `formatString:` line. If absent, add it indented at the same level as other measure properties (one tab deeper than `measure`). For a General-formatted measure there may be an `annotation PBI_FormatHint` — remove or update it (`{"isGeneralNumber":true}` ⇒ inconsistent with an explicit currency/percent string; safe to delete the annotation when setting an explicit format).

**Rename a measure** — DAX references by name: search the **whole project** for `[Old Name]` (other TMDL files, `reportExtensions.json`, visual.json `Property` values, filter definitions) and update all. Safer path: advise doing renames in Desktop/Tabular Editor which fix references; do the mechanical rename only when the user understands the blast radius.

**Add a measure** — append inside the right `table` block, after existing measures, matching indentation; include `lineageTag` (new GUID) and `formatString`.

**Move to a display folder** — set `displayFolder:`; nested with `\`.

**Add a description** — `///` line(s) immediately above `measure`.

**Report-level measures (thin reports)** — when the report has `byConnection` and no local model, measures live in `Report/definition/reportExtensions.json`:
```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/reportExtension/1.0.0/schema.json",
  "name": "extension",
  "entities": [
    { "name": "Sales",
      "measures": [
        { "name": "Total Sales LY",
          "dataType": "Double",
          "expression": "CALCULATE([Total Sales], SAMEPERIODLASTYEAR('Date'[Date]))",
          "formatString": "#,##0",
          "displayFolder": "Revenue",
          "hidden": false } ] } ]
}
```
`entities[].name` must match a semantic-model table. Required per measure: `name`, `dataType`, `expression`.

## Columns (for context — format fixes often hit columns too)

```tmdl
	column 'Order Date'
		dataType: dateTime
		formatString: yyyy-MMM-dd
		lineageTag: 4184d53e-cd2d-4cbe-b8cb-04c72a750bc4
		summarizeBy: none
		sourceColumn: OrderDate

		annotation SummarizationSetBy = Automatic
```
Column-only properties: `dataType` (`int64`, `double`, `decimal`, `string`, `dateTime`, `boolean`), `sourceColumn`, `sortByColumn`, `summarizeBy` (`none`/`sum`/…), `isKey`, `isNameInferred`, `isAvailableInMdx`, `dataCategory`.

## Model-level gotchas

- `model.tmdl` lists tables via `ref table <Name>` entries — adding a brand-new table file requires a matching `ref` (check how existing entries look in that project).
- Perspectives (`perspectives/*.tmdl`) reference objects by name: renames must be propagated (`perspectiveMeasure`).
- Cultures/translations (`cultures/*.tmdl`) may carry `linguisticMetadata` JSON containing object names.
- Calculation groups: `calculationGroup` tables with `calculationItem` children — format string of items via `formatStringDefinition` on the item.
- Validation: no duplicate property per object, tabs only, quotes on special names, backticks around conflicting expressions. There is no offline TMDL validator in this environment — a careful diff review is the check; Desktop validates on open.
