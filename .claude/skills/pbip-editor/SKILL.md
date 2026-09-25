---
name: pbip-editor
description: Edit Power BI Project (PBIP) files saved with TMDL semantic model format and PBIR enhanced report format. Use this skill whenever the user wants to modify a Power BI report or model as code — fixing visual design attributes (titles, fonts, colors, borders, backgrounds, positions, data labels, axes), editing measures (DAX, format strings, display folders, descriptions), adding or editing visual calculations, batch-updating formatting across visuals or pages, or working with any file inside a *.Report/definition or *.SemanticModel/definition folder. Trigger on mentions of PBIP, PBIR, TMDL, visual.json, page.json, *.tmdl files, "fix the visuals", "change formatting in the report files", "edit the semantic model as code", or any request to programmatically change Power BI report/model metadata.
---

# PBIP Editor (TMDL + PBIR)

Edit Power BI Projects saved as source-control-friendly files:

- **Report** → `<name>.Report/definition/` — PBIR JSON files (one file per page/visual/bookmark)
- **Semantic model** → `<name>.SemanticModel/definition/` — TMDL files (one file per table)

## Reference files — read before editing

| Task | Read first |
|---|---|
| Locate files, understand folder layout, safety rules | `references/pbir-structure.md` |
| Edit a visual: position, size, type, fields, sorting | `references/pbir-visuals.md` |
| Fix design attrs: title, colors, fonts, background, border, labels, axes, conditional formatting | `references/pbir-formatting.md` |
| Add/edit visual calculations | `references/visual-calculations.md` |
| Edit measures: DAX, formatString, displayFolder, dynamic format strings; TMDL syntax | `references/tmdl-measures.md` |
| Batch changes across many visuals/pages/reports | `references/batch-patterns.md` |

For a design-fix request ("make all titles 14pt Segoe UI", "give KPI cards rounded borders"), read `pbir-structure.md` + `pbir-formatting.md`. For measure work, read `tmdl-measures.md`. For visual calculations, read `pbir-visuals.md` + `visual-calculations.md`.

## Workflow

1. **Locate the project.** Find `*.pbip`, the `*.Report/` and `*.SemanticModel/` folders. Confirm PBIR format: `definition.pbir` has `"version": "4.0"`+ and a `definition/` folder exists (not a monolithic `report.json` — that is PBIR-Legacy, which this skill does not edit).
2. **Recommend a backup/commit.** These edits are applied by Power BI Desktop on next open; a bad edit can block the report from opening. If the folder is in git, suggest committing first.
3. **Read before writing.** Always read the target file fully. PBIR files carry a `$schema` URL — keep it unchanged unless a property you need requires a newer schema version (see structure reference).
4. **Edit surgically.** Preserve `name` values, `lineageTag`s, `queryRef`s and unknown properties byte-for-byte. Change only what the task requires — small diffs are the entire point of this format.
5. **Validate.** After editing JSON: parse every touched file (`python3 -m json.tool`). After editing TMDL: check indentation is tabs, names with spaces/special chars are single-quoted, and no property appears twice on one object.
6. **Report back.** List every file touched and what changed; remind the user Power BI Desktop validates on open, and blocking errors will name the offending file.

## Hard rules

- **Never invent property names.** PBIR schemas set `additionalProperties: false` almost everywhere — an unknown property is a blocking error. If unsure a property exists, check the schema URL in the file's `$schema` or the reference files here.
- **Literal value encoding is strict** (`'text'` in single quotes, numbers with `D` suffix, bare `true`/`false`). Wrong encoding silently breaks formatting. See `pbir-formatting.md`.
- **Don't touch** `report.json` (PBIR-Legacy), `mobileState.json`, `semanticModelDiagramLayout.json`, `.pbi/localSettings.json`, `cache.abf`, or `.platform` — these don't support external editing or are user/machine-local.
- **Object `name` ≠ display title.** Visual/page `name` is a stable ID referenced by bookmarks, drillthrough, and filters. Renaming breaks references.
- **TMDL is tab-indented.** The serializer emits tabs; mixing spaces breaks parsing.
- **Match the existing schema version.** When adding new files (e.g., a new visual.json), copy the `$schema` version from a sibling file in the same project, not the newest version available online.
