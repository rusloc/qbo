# Fixing Design Attributes in visual.json

Formatting lives in two dictionaries under `visual`:

- **`visualContainerObjects`** — the container chrome, same for every visual type: `title`, `subTitle`, `divider`, `spacing`, `background`, `padding`, `lockAspect`, `general`, `border`, `dropShadow`, `visualLink`, `visualTooltip`, `stylePreset`, `visualHeader`, `visualHeaderTooltip`.
- **`objects`** — visual-type-specific formatting (axes, labels, data colors, grid…). Mirrors the Format pane sections.

Both share one structure: `objectName → array of { selector?, properties }`.

```json
"visualContainerObjects": {
  "title": [
    { "properties": {
        "show":      { "expr": { "Literal": { "Value": "true" } } },
        "text":      { "expr": { "Literal": { "Value": "'Revenue by Month'" } } },
        "fontSize":  { "expr": { "Literal": { "Value": "14D" } } },
        "fontFamily":{ "expr": { "Literal": { "Value": "'Segoe UI Semibold'" } } },
        "fontColor": { "solid": { "color": { "expr": { "Literal": { "Value": "'#252423'" } } } } },
        "alignment": { "expr": { "Literal": { "Value": "'center'" } } }
    } }
  ]
}
```

## Value encoding — the #1 source of broken edits

Every property value is an expression. Get the literal encoding exactly right:

| Type | Encoding | Example |
|---|---|---|
| Text/enum | single quotes **inside** the JSON string | `"Value": "'Segoe UI'"`, `"Value": "'center'"` |
| Number | `D` suffix (double) | `"Value": "12D"`, `"Value": "0.5D"` |
| Integer (rare, e.g. z-order-ish props) | `L` suffix | `"Value": "2L"` |
| Boolean | bare | `"Value": "true"` / `"Value": "false"` |
| Null (reset to default) | bare | `"Value": "null"` |
| Color (fixed) | solid wrapper + hex text | `{"solid": {"color": {"expr": {"Literal": {"Value": "'#118DFF'"}}}}}` |
| Color (theme) | ThemeDataColor | `{"solid": {"color": {"expr": {"ThemeDataColor": {"ColorId": 2, "Percent": 0.4}}}}}` |

ThemeDataColor: `ColorId` 0–7 = theme data colors (0 is first), plus specials (foreground/background variants); `Percent` = shade (-0.6…0.6, 0 = base). Prefer ThemeDataColor when the user wants theme-consistent styling; literal hex when they give exact colors.

**Removing a property** = delete its key (falls back to theme/default). Setting `"Value": "null"` explicitly resets. Removing the whole object entry (e.g., the `title` array) reverts the entire card to defaults.

## Selectors — scoping a property

No `selector` → applies to the whole visual. With `selector`:

```json
// Per-field (series/column/measure) — metadata = the projection's queryRef
{ "selector": { "metadata": "Sales.Total Sales" },
  "properties": { "dataColor": { "solid": { "color": { "expr": { "Literal": { "Value": "'#E66C37'" } } } } } } }

// Per data point (e.g., one pie slice / one category value)
{ "selector": { "data": [ { "scopeId": { "Comparison": { "ComparisonKind": 0,
      "Left": { "Column": { "Expression": { "SourceRef": { "Entity": "Product" } }, "Property": "Category" } },
      "Right": { "Literal": { "Value": "'Bikes'" } } } } } ] },
  "properties": { … } }

// All series wildcard
{ "selector": { "data": [ { "dataViewWildcard": { "matchingOption": 1 } } ] }, "properties": { … } }

// User-defined id (used by some objects, e.g. reference lines: "id": "0")
{ "selector": { "id": "0" }, "properties": { … } }
```

Order matters: later entries in an object's array win over earlier ones at equal scope; scoped selectors win over unscoped.

## visualContainerObjects catalogue (design attrs)

| Object | Properties |
|---|---|
| `title` | `show`, `text`, `heading` (e.g. `'Heading1'`…), `titleWrap`, `fontColor`, `background`, `alignment` (`'left'/'center'/'right'`), `fontSize`, `bold`, `italic`, `underline`, `fontFamily` |
| `subTitle` | same set as title + `titleWrap` |
| `divider` | `show`, `color`, `style` (`'solid'/'dashed'/'dotted'`), `width`, `ignorePadding` |
| `spacing` | `customizeSpacing`, `spaceBelowTitle`, `spaceBelowSubTitle`, `spaceBelowTitleArea` |
| `background` | `show`, `color`, `transparency` (0–100, `D`) |
| `border` | `show`, `color`, `radius` (px, `D`), `width` |
| `dropShadow` | `show`, `preset` (`'Custom'` or positions), `position` (`'Outer'/'Inner'`), `color`, `transparency`, `shadowSpread`, `shadowBlur`, `angle`, `shadowDistance` |
| `padding` | `top`, `bottom`, `left`, `right` (px, `D`) |
| `general` | `altText`, `keepLayerOrder`, `responsive` |
| `lockAspect` | `show` |
| `visualHeader` | `show` + per-button toggles: `showVisualInformationButton`, `showVisualWarningButton`, `showDrillUpButton`, `showDrillToggleButton`, `showDrillDownLevelButton`, `showDrillDownExpandButton`, `showPinButton`, `showFilterRestatementButton`, `showFocusModeButton`, `showCopyVisualImageButton`, `showOptionsMenu`, `showSmartNarrativeButton`, … |
| `visualTooltip` | `show`, `type` (`'Default'`/`'ReportPage'`), `section` (tooltip page name), `titleFontColor`, `valueFontColor`, `background`, … |
| `visualLink` | `show`, `type` (`'Back'/'Bookmark'/'PageNavigation'/'WebUrl'/…`), `navigationSection`, `bookmark`, `webUrl`, `tooltip` |
| `stylePreset` | `name` (e.g. `'None'`, theme style preset name) |

## Common `objects` per visual type

Names mirror the Format pane. Frequent ones (not exhaustive — unknown-but-valid names exist per visual; when unsure, set the property in Desktop once and read the diff):

| Visual | Objects |
|---|---|
| Cartesian charts | `categoryAxis` (x), `valueAxis` (y), `legend`, `labels` (data labels), `dataPoint` (colors), `plotArea`, `gridlines`, `zoom`, `smallMultiplesLayout`, `referenceLine`, `y1AxisReferenceLine`, `errorBars`, `seriesLabels`, `lineStyles` (line charts: `strokeWidth`, `lineStyle`, `showMarker`, `markerShape`…), `trend`, `general` |
| Card (classic `card`) | `labels` (the value: `color`, `fontSize`, `fontFamily`, `labelDisplayUnits`, `labelPrecision`), `categoryLabels`, `wordWrap` |
| New card (`cardVisual`) | `value`, `label`, `callout`, `cards`, `layout`, `image`, `accentBar`, `referenceLabels` |
| KPI | `indicator`, `goals`, `trendline`, `dateLabel` |
| Table (`tableEx`) | `grid` (`gridVertical`, `gridHorizontal`, `rowPadding`, `outline*`, `textSize`), `columnHeaders` (`fontColor`, `backColor`, `bold`, `fontSize`, `alignment`, `wordWrap`, `autoSizeColumnWidth`), `values` (`fontColor*`, `backColor*`, `alternate*`), `total`, `columnFormatting`, `columnWidth` (with `metadata` selectors) |
| Matrix (`pivotTable`) | as table + `rowHeaders`, `subTotals`, `columnTotal`, `rowTotal`, `expandCollapse`, `stepped` |
| Slicer | `data`/`general`, `selection` (`selectAllCheckboxEnabled`, `singleSelect`, `strictSingleSelect`), `header`, `items` (`fontColor`, `background`, `outline`), `date`/`numericInputStyle`, `slider` |
| Pie/Donut | `legend`, `labels` (`labelStyle` e.g. `'Category, percent of total'`), `dataPoint`, `slices` |
| Gauge | `axis`, `dataLabels`, `calloutValue`, `target` |
| Textbox | content is in `objects.general[0].properties.paragraphs` (rich-text runs: `textRuns` with `value` + `textStyle`) |
| Action button / shape | `fill`, `outline`, `text`, `icon`, `shape`, `rotation` — many properties use **state selectors** `{"id": "default"}`, `"hover"`, `"selected"`, `"disabled"` |
| Azure map | `mapControls`, `mapStyles`, `bubbles`/`bubbleLayer`, `heatMapLayer`, `legend` |

### Frequently-used property names inside those objects

- Data labels (`labels`): `show`, `color`, `labelDisplayUnits` (`0D` auto, `1D` none, `1000D` K, `1000000D` M…), `labelPrecision` (decimals), `fontSize`, `fontFamily`, `bold`, `labelPosition`, `labelOrientation`, `showAll`, `enableBackground`, `backgroundColor`, `backgroundTransparency`.
- Axes (`categoryAxis`/`valueAxis`): `show`, `axisScale` (`'linear'/'log'`), `start`, `end`, `labelColor`, `fontSize`, `fontFamily`, `titleText`, `showAxisTitle`, `titleColor`, `titleFontSize`, `gridlineShow`, `gridlineColor`, `gridlineStyle`, `innerPadding`, `preferredCategoryWidth`, `maxMarginFactor`, `concatenateLabels`.
- Legend: `show`, `position` (`'Top'`, `'Bottom'`, `'Left'`, `'Right'`, `'TopCenter'`, …), `showTitle`, `titleText`, `labelColor`, `fontSize`, `fontFamily`.
- Data colors (`dataPoint`): `defaultColor`, `showAllDataPoints`, `fill` (with data/metadata selector per series/category).

## Conditional formatting

Field-driven color (fx button) replaces the literal with a `FillRule` or `Conditional` expression:

```json
// Gradient (linear2/linear3) driven by a measure
"backColor": { "solid": { "color": { "expr": { "FillRule": {
  "Input": { "Measure": { "Expression": { "SourceRef": { "Entity": "Sales" } }, "Property": "Margin %" } },
  "FillRule": { "linearGradient2": {
    "min": { "color": { "expr": { "Literal": { "Value": "'#FEE2E2'" } } } },
    "max": { "color": { "expr": { "Literal": { "Value": "'#16A34A'" } } } },
    "nullColoringStrategy": { "strategy": { "expr": { "Literal": { "Value": "'asZero'" } } } } } }
} } } } }

// Rules / field value
"fontColor": { "solid": { "color": { "expr": { "Conditional": { "Cases": [
  { "Condition": { "Comparison": { "ComparisonKind": 2,
      "Left": { "Measure": { "Expression": { "SourceRef": { "Entity": "Sales" } }, "Property": "Growth" } },
      "Right": { "Literal": { "Value": "0D" } } } },
    "Value": { "Literal": { "Value": "'#107C10'" } } } ],
  "DefaultValue": { "Literal": { "Value": "'#D13438'" } } } } } } }
```
`ComparisonKind`: 0 `=`, 1 `>`, 2 `>=`, 3 `<`, 4 `<=`. In table/matrix, conditional `backColor`/`fontColor` go under `objects.values` with a `{"metadata": "<queryRef>"}` selector.

## Recipes

**Set/override a visual title** — `visualContainerObjects.title[0].properties.text` (+ `show: true`). If no `title` key exists, create it.

**Batch: same title style on every visual** — loop all `visual.json`; skip `visualGroup` files and decorative types (`textbox`, `shape`, `image`, `actionButton`) unless asked; merge properties into `title[0].properties`, preserving each visual's `text`.

**Rounded corners + subtle shadow on cards**:
```json
"border":     [ { "properties": { "show": { "expr": { "Literal": { "Value": "true" } } },
                                   "radius": { "expr": { "Literal": { "Value": "8D" } } } } } ],
"dropShadow": [ { "properties": { "show": { "expr": { "Literal": { "Value": "true" } } },
                                   "preset": { "expr": { "Literal": { "Value": "'BottomRight'" } } } } } ]
```

**Change a series color** — `objects.dataPoint`, entry with `{"selector": {"metadata": "<queryRef of the series/measure>"}}`, property `fill`.

**Hide all visual-level filter cards** — every `filterConfig.filters[*].isHiddenInViewMode = true` across all visual.json.

**Format-string fix at visual scope only** — set `format` on the projection (see pbir-visuals.md). Model-wide → change the measure's `formatString` in TMDL instead (preferred for consistency; see tmdl-measures.md).

**Theme-level fixes** — if the same change is wanted "everywhere, always", consider editing the report theme (`StaticResources/RegisteredResources/<theme>.json`, referenced from `report.json` `themeCollection.customTheme`) instead of per-visual objects; per-visual `objects` override the theme.

## Verification checklist after formatting edits

1. `python3 -m json.tool <file>` on every touched file.
2. Every literal follows the encoding table (grep for `"Value": "` and eyeball suffixes/quotes).
3. No new top-level keys added to `visual` or the container beyond schema-known ones.
4. Selectors reference existing `queryRef`s (cross-check `queryState`).
