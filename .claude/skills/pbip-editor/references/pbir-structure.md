# PBIP Project Structure (TMDL + PBIR)

## Top level

```
MyProject.pbip                      ← tiny pointer file, opens the project in PBI Desktop
MyProject.Report/
├── .platform                       ← Fabric/Git metadata — do not edit
├── .pbi/localSettings.json         ← user/machine-local — do not edit, gitignored
├── definition.pbir                 ← report properties + semantic model reference
├── definition/                     ← PBIR report definition (this is what you edit)
├── StaticResources/
│   └── RegisteredResources/        ← themes, images (editable; must be registered in report)
├── CustomVisuals/                  ← private custom visuals metadata
├── mobileState.json                ← do not edit
└── semanticModelDiagramLayout.json ← do not edit
MyProject.SemanticModel/
├── .platform
├── .pbi/
│   ├── localSettings.json          ← do not edit
│   └── editorSettings.json
├── definition.pbism                ← model properties file
├── definition/                     ← TMDL model definition (this is what you edit)
└── diagramLayout.json              ← do not edit
```

`definition.pbir` — confirms format and links the model:

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
  "version": "4.0",
  "datasetReference": {
    "byPath": { "path": "../MyProject.SemanticModel" }
  }
}
```

- `version` `"4.0"`+ AND a `definition/` folder → PBIR (this skill).
- `version` `"1.0"` or a `report.json` file → PBIR-Legacy. Not externally editable; tell the user to upgrade via Desktop (Save with the PBIR preview feature on → "Upgrade").
- `byPath` = thick report (model opens in edit mode alongside). `byConnection` = thin report pointing at a published model; measures then usually live in `reportExtensions.json` (report-level measures), not TMDL.

## Report definition folder (PBIR)

```
definition/
├── version.json                    ← PBIR version metadata (leave alone)
├── report.json                     ← report-level: theme, filters, settings, annotations
├── reportExtensions.json           ← report-level measures (optional)
├── bookmarks/
│   ├── bookmarks.json              ← order & groups
│   └── <bookmarkName>.bookmark.json
└── pages/
    ├── pages.json                  ← page order + activePageName
    └── <pageName>/                 ← one folder per page (name = stable ID)
        ├── page.json               ← page size, display name, filters, wallpaper, formatting
        └── visuals/
            └── <visualName>/       ← one folder per visual (name = stable ID)
                ├── visual.json     ← THE visual definition (position, type, data, formatting)
                └── mobile.json     ← optional mobile layout
```

### Names and IDs

- Folder names = the `name` property inside the JSON = 20-char hex ID like `90c2e07d8e84e7d5c026` (new objects may be shorter GUID-ish strings). Word characters and hyphens only.
- `page.json` → `displayName` is the tab caption the user sees. To find a page by its caption: grep `displayName` across `pages/*/page.json`.
- To find a visual: users can right-click a visual in Desktop → *Copy object name* (enable in Options → Report settings → Report objects). Otherwise identify by `visualType` + position + bound fields.
- Renaming `name`/folders is allowed but breaks bookmark/drillthrough/`activePageName` references — avoid unless asked; if done, rename folder AND `name` property AND every reference, then restart Desktop.

### Schema versions

Every PBIR JSON starts with a `$schema` URL that pins its version, e.g.:

```
https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.9.0/schema.json
```

All schemas + changelogs: https://github.com/microsoft/json-schemas/tree/main/fabric/item/report/definition

Rules of thumb:
- Editing an existing file → keep its `$schema` as-is. Desktop upgrades versions itself on save.
- Adding a new file → copy `$schema` from a sibling file of the same type in the same project.
- Only bump a version if a property you must add doesn't exist in the pinned version (check the CHANGELOG.md in the schema repo folder).
- Recent visualContainer versions: 2.3.0 (Oct 2025, card GA), 2.5.0 (modern tooltips), 2.7.0 (Mar 2026), 2.9.0 (May 2026). Projects saved by older Desktop builds commonly pin 1.x–2.x — that's fine.

## Semantic model definition folder (TMDL)

```
definition/
├── database.tmdl                   ← compatibility level
├── model.tmdl                      ← model settings, table refs, annotations
├── expressions.tmdl                ← shared M expressions / parameters
├── relationships.tmdl              ← all relationships
├── cultures/en-US.tmdl             ← linguistic metadata
├── perspectives/*.tmdl
├── roles/*.tmdl                    ← RLS
└── tables/
    └── <Table Name>.tmdl           ← columns, measures, hierarchies, partitions per table
```

Measures live inside `tables/*.tmdl` (or `reportExtensions.json` for thin reports). See `tmdl-measures.md`.

## Safety & validation

1. Suggest `git commit` (or a folder copy) before edits.
2. Whitelist of externally editable files: `definition/` contents (both report & model), `definition.pbir`, `StaticResources/RegisteredResources/*` (already-registered files only).
3. After edits, Desktop validates on open:
   - **Blocking errors** (bad schema, unknown property, missing required property) stop the report from loading and name the offending file.
   - **Non-blocking errors** (e.g., stale `activePageName`) are auto-fixed with a warning.
4. Filters applied in the UI can persist *data values* into visual.json/bookmarks (e.g., `'Company' = 'Contoso'`) — treat filter values as data, don't "clean them up".
5. Service limits: 1,000 pages/report, 1,000 visuals/page, 300 MB report files.

## Quick file-location recipes

```bash
# All visual.json files
find . -path '*/visuals/*/visual.json'

# Pages by display name
grep -r '"displayName"' */definition/pages/*/page.json

# All visuals of a given type
grep -rl '"visualType": "card"' --include=visual.json .

# Which visuals use measure [Total Sales]
grep -rl 'Total Sales' --include=visual.json .

# All measures in the model
grep -rn $'\tmeasure ' *.SemanticModel/definition/tables/*.tmdl
```
