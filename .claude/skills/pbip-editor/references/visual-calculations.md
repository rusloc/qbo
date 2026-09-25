# Visual Calculations in PBIR

Visual calculations are DAX expressions stored **inside the visual** (visual.json), operating on the visual's own result grid — not in the semantic model. They appear as a projection whose `field` is a `NativeVisualCalculation`.

## Shape

A visual calc lives in `visual.query.queryState.<Role>.projections[]` alongside normal fields:

```json
"Values": {
  "projections": [
    {
      "field": { "Column": { "Expression": { "SourceRef": { "Entity": "Dim Product" } }, "Property": "Product" } },
      "queryRef": "Dim Product.Product",
      "nativeQueryRef": "Product"
    },
    {
      "field": { "Measure": { "Expression": { "SourceRef": { "Entity": "Fact Sales" } }, "Property": "Sum of Sales" } },
      "queryRef": "Fact Sales.Sum of Sales",
      "nativeQueryRef": "Sum of Sales"
    },
    {
      "field": {
        "NativeVisualCalculation": {
          "Language": "dax",
          "Expression": "[Sum of Sales] - PREVIOUS([Sum of Sales])",
          "Name": "Versus previous"
        }
      },
      "queryRef": "select",
      "nativeQueryRef": "Versus previous"
    }
  ]
}
```

### NativeVisualCalculation properties (all schema-allowed keys)

| Key | Required | Notes |
|---|---|---|
| `Language` | yes | Always `"dax"` (schema const). |
| `Expression` | yes | The visual-calc DAX. References other fields **by `nativeQueryRef` in square brackets**: `[Sum of Sales]`, `[Versus previous]`. |
| `Name` | yes | Display name of the calculation. Keep equal to the projection's `nativeQueryRef`. |
| `DataType` | no | `"Text"`, `"Double"`, `"Decimal"`, `"Integer"`, `"Boolean"`, `"Date"`, `"DateTime"`, … |

### Projection wrapper rules

- `queryRef` — Desktop typically emits a generic ref (`"select"`, or a unique variant when several calcs exist: `"select1"`, `"select2"`). It must be **unique within the visual** — when adding a second calc next to an existing `"select"`, use a distinct value.
- `nativeQueryRef` — the handle other visual calcs use to reference this one; must be unique within the visual.
- **Formatting a visual calc**: add `"format": "0.0%"` (VBA-style format string) on the projection — `NativeVisualCalculation` itself has no Format key.
- **Hidden helper fields**: a field only needed as input for a calc carries `"hidden": true` on its projection. It's queried but not displayed. To "unhide", delete the key.

## Visual-calc DAX essentials

Runs over the visual matrix (rows/columns as laid out), not the model:

- Templates/functions: `PREVIOUS`, `NEXT`, `FIRST`, `LAST`, `RUNNINGSUM`, `MOVINGAVERAGE`, `COLLAPSE`, `COLLAPSEALL`, `EXPAND`, `EXPANDALL`, `LOOKUP`, `LOOKUPWITHTOTALS`, `RANGE` — plus regular scalar DAX (`DIVIDE`, `IF`, …).
- Optional axis argument: `ROWS`, `COLUMNS`, `ROWS COLUMNS`. E.g. `RUNNINGSUM([Sales], COLUMNS)`.
- Only fields **on the visual** are referenceable — by `nativeQueryRef` in brackets. No table references, no model measures that aren't projected.
- Model measures used only as calc inputs → keep them projected with `"hidden": true`.

## Recipes

**Add a running total to a table (`tableEx`)** — append to `Values.projections`:
```json
{
  "field": { "NativeVisualCalculation": {
      "Language": "dax",
      "Expression": "RUNNINGSUM([Total Sales])",
      "Name": "Running Total" } },
  "queryRef": "select",
  "nativeQueryRef": "Running Total",
  "format": "#,0"
}
```
(If a `"select"` queryRef already exists in this visual, name it `"select1"` etc.)

**% of parent in a matrix**:
```json
"Expression": "DIVIDE([Total Sales], COLLAPSE([Total Sales], ROWS))"
```

**Edit an existing calc** — change only `Expression` (and `Name`/`nativeQueryRef` in sync if renaming; then update every other calc that references the old `nativeQueryRef`).

**Delete a calc** — remove its projection; also remove `hidden: true` helpers no other calc uses; check `sortDefinition` and `objects` selectors for references to its `queryRef`.

## Gotchas

- Visual calcs are per-visual: copying a visual.json copies its calcs; nothing lands in TMDL.
- `expansionStates` and sort definitions may reference calc queryRefs — keep in sync when renaming.
- If the user wants the number reusable across visuals → recommend a model measure (TMDL) or report-level measure (`reportExtensions.json`) instead; see tmdl-measures.md.
- Visual calcs don't support all DAX (no CALCULATE-style filter context manipulation); keep expressions in the visual-calc subset above.
