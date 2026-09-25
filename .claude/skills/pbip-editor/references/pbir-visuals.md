# visual.json Anatomy

Schema: `.../report/definition/visualContainer/<version>/schema.json`. Nesting is strict (`additionalProperties: false`) — property placement errors are blocking errors.

## Top-level shape

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.9.0/schema.json",
  "name": "a1b2c3d4e5f6a7b8c9d0",
  "position": { "x": 40, "y": 120, "z": 1000, "width": 480, "height": 320, "tabOrder": 2 },
  "visual": { ... },
  "filterConfig": { ... },
  "isHidden": false,
  "parentGroupName": "…",
  "visualGroup": { ... },
  "annotations": [ { "name": "…", "value": "…" } ],
  "howCreated": "InsertVisualButton"
}
```

| Property | Notes |
|---|---|
| `name` | Unique per page; referenced by bookmarks/interactions. Don't change. |
| `position` | `x`,`y` top-left in px on the page canvas; `z` stacking; `width`/`height` px; optional `tabOrder`, `angle`. Page canvas size is in `page.json` (`width`/`height`, commonly 1280×720). |
| `visual` | The chart itself — type, data, formatting. Mutually exclusive with `visualGroup` (grouping container). |
| `filterConfig` | Visual-level filters (same structure as page/report filters). |
| `isHidden` | Hidden in view mode (still in selection pane). |
| `annotations` | Free name/value pairs, ignored by Desktop — safe for tooling metadata. |

## `visual` object

```json
"visual": {
  "visualType": "clusteredColumnChart",
  "query": {
    "queryState": { ... },
    "sortDefinition": { ... },
    "options": { ... }
  },
  "objects": { ... },                    // per-visual-type formatting (see pbir-formatting.md)
  "visualContainerObjects": { ... },     // container formatting: title, background, border… (see pbir-formatting.md)
  "drillFilterOtherVisuals": true,
  "autoSelectVisualType": false,
  "expansionStates": [ ... ],            // expanded matrix/hierarchy nodes — data-dependent, leave alone
  "syncGroup": { "groupName": "…", "fieldChanges": true, "filterChanges": true }   // slicers only
}
```

Common `visualType` values: `card`, `cardVisual` (new card), `multiRowCard`, `kpi`, `gauge`, `slicer`, `advancedSlicerVisual` (button slicer), `listSlicer`, `textSlicer`, `tableEx` (table), `pivotTable` (matrix), `barChart`, `clusteredBarChart`, `columnChart`, `clusteredColumnChart`, `hundredPercentStackedBarChart`, `hundredPercentStackedColumnChart`, `lineChart`, `areaChart`, `stackedAreaChart`, `lineStackedColumnComboChart`, `lineClusteredColumnComboChart`, `ribbonChart`, `waterfallChart`, `funnel`, `pieChart`, `donutChart`, `treemap`, `scatterChart`, `map`, `filledMap`, `azureMap`, `shapeMap`, `decompositionTreeVisual`, `keyDriversVisual`, `aiNarratives`, `scriptVisual` (R), `pythonVisual`, `textbox`, `image`, `actionButton`, `shape`. Custom visuals use their GUID-style name.

## `queryState` — what data is on the visual

A dictionary of **roles** (buckets in the field well) → projections. Role names vary per visual type:

| Visual family | Typical roles |
|---|---|
| Cartesian (bar/column/line/area) | `Category`, `Y`, `Y2`, `Series`, `Tooltips` |
| Table | `Values` |
| Matrix | `Rows`, `Columns`, `Values` |
| Card / KPI | `Values` / `Indicator`, `TrendAxis`, `Goals` |
| Pie/Donut | `Category`, `Y`, `Details` |
| Scatter | `Category`, `X`, `Y`, `Size`, `Details` |
| Slicer | `Values` |

```json
"queryState": {
  "Category": {
    "projections": [
      {
        "field": { "Column": { "Expression": { "SourceRef": { "Entity": "Date" } }, "Property": "Month" } },
        "queryRef": "Date.Month",
        "nativeQueryRef": "Month",
        "active": true
      }
    ]
  },
  "Y": {
    "projections": [
      {
        "field": { "Measure": { "Expression": { "SourceRef": { "Entity": "Sales" } }, "Property": "Total Sales" } },
        "queryRef": "Sales.Total Sales",
        "nativeQueryRef": "Total Sales",
        "displayName": "Revenue",
        "format": "#,0.0%"
      }
    ]
  }
}
```

### Projection properties

| Property | Meaning |
|---|---|
| `field` | The expression (see field kinds below). Required. |
| `queryRef` | Unique-per-visual name; **the key used by `objects` selectors, sortDefinition, columnWidth etc.** Convention: `Table.Field`, aggregations as `Sum(Table.Column)`. Required. |
| `nativeQueryRef` | Name used to reference this field **inside visual calculation DAX**. |
| `displayName` | Rename scoped to this visual only. |
| `format` | Format string override scoped to this visual (VBA-style, e.g. `"#,0"`, `"0.0%"`, `"yyyy-MMM-dd"`). |
| `active` | Drill state for hierarchies. |
| `hidden` | Field is queried but not shown — used with visual calculations. |

### Field kinds

```json
// Model column
{ "Column":  { "Expression": { "SourceRef": { "Entity": "Sales" } }, "Property": "Region" } }

// Model measure
{ "Measure": { "Expression": { "SourceRef": { "Entity": "Sales" } }, "Property": "Total Sales" } }

// Implicit aggregation of a column (Function: 0=Sum 1=Avg 2=Count 3=Min 4=Max 5=CountNonNull)
{ "Aggregation": {
    "Expression": { "Column": { "Expression": { "SourceRef": { "Entity": "Sales" } }, "Property": "Amount" } },
    "Function": 0 } }

// Hierarchy level
{ "HierarchyLevel": {
    "Expression": { "Hierarchy": { "Expression": { "SourceRef": { "Entity": "Date" } }, "Hierarchy": "Date Hierarchy" } },
    "Level": "Year" } }

// Visual calculation — see visual-calculations.md
{ "NativeVisualCalculation": { "Language": "dax", "Expression": "…", "Name": "…" } }
```

`Entity` is the **table name** in the semantic model; `Property` the column/measure name. When editing, keep `Entity`/`Property` exactly matching the model (TMDL) or the visual breaks with "field not found".

## Sorting

```json
"sortDefinition": {
  "sort": [ { "field": { "Measure": { "Expression": { "SourceRef": { "Entity": "Sales" } }, "Property": "Total Sales" } },
              "direction": "Descending" } ],
  "isDefaultSort": true
}
```
`direction`: `Ascending` | `Descending`.

## filterConfig (visual-level filters)

```json
"filterConfig": {
  "filters": [
    {
      "name": "f1a2b3…",
      "field": { "Column": { "Expression": { "SourceRef": { "Entity": "Product" } }, "Property": "Category" } },
      "type": "Categorical",
      "filter": {
        "Version": 2,
        "From": [ { "Name": "p", "Entity": "Product", "Type": 0 } ],
        "Where": [ { "Condition": { "In": {
          "Expressions": [ { "Column": { "Expression": { "SourceRef": { "Source": "p" } }, "Property": "Category" } } ],
          "Values": [ [ { "Literal": { "Value": "'Bikes'" } } ] ] } } } ]
      },
      "isHiddenInViewMode": false,
      "isLockedInViewMode": false
    }
  ]
}
```
`type`: `Categorical` | `Advanced` | `TopN` | `RelativeDate` | `RelativeTime` | `Passthrough` | `VisualTopN`. Omit `filter` for an empty filter card. Batch-hiding filter pane cards = set `isHiddenInViewMode: true` on each filter.

## page.json essentials

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
  "name": "c2d9b4b1487b2eb30e98",
  "displayName": "Overview",
  "displayOption": "FitToPage",
  "height": 720, "width": 1280,
  "visibility": "AlwaysVisible",
  "objects": { "background": [ … ], "outspace": [ … ], "outspacePane": [ … ], "personalizeVisual": [ … ] },
  "filterConfig": { … }
}
```
`visibility`: `AlwaysVisible` | `HiddenInViewMode`. Page background = `objects.background`; wallpaper (outside canvas) = `objects.outspace`.

## Groups

A grouping container is a visual.json with `visualGroup` instead of `visual`:
```json
"visualGroup": { "displayName": "KPI Row", "groupMode": "ScaleMode" }
```
Members carry `"parentGroupName": "<group's name>"` and their `position` stays in **absolute page coordinates**.
