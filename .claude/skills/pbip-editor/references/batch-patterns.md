# Batch Edit Patterns

Programmatic changes across many visuals/pages/reports. Python is preferred (round-trips JSON faithfully); always parse → modify → dump, never regex-edit JSON.

## Canonical walker

```python
import json, glob, os

def walk_visuals(report_dir):
    """Yield (path, data) for every visual.json under a Report folder."""
    for path in sorted(glob.glob(os.path.join(
            report_dir, "definition", "pages", "*", "visuals", "*", "visual.json"))):
        with open(path, encoding="utf-8") as f:
            yield path, json.load(f)

def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
```

Match Desktop's serialization: 2-space indent, UTF-8, `ensure_ascii=False`, trailing newline. Keep key order (Python dicts preserve insertion order — don't sort keys).

## Helper: literal wrappers

```python
lit  = lambda v: {"expr": {"Literal": {"Value": v}}}
text = lambda s: lit(f"'{s}'")           # text/enum
num  = lambda n: lit(f"{n}D")            # number
flag = lambda b: lit("true" if b else "false")
color= lambda hexcode: {"solid": {"color": lit(f"'{hexcode}'")}}
theme= lambda cid, pct=0: {"solid": {"color": {"expr": {"ThemeDataColor": {"ColorId": cid, "Percent": pct}}}}}
```

## Pattern: merge container formatting into every visual

```python
DECORATIVE = {"textbox", "shape", "image", "actionButton"}

def set_vc_object(data, obj_name, props: dict):
    """Merge props into the first unscoped entry of a visualContainerObjects object."""
    visual = data.get("visual")
    if not visual:                      # visualGroup container — skip
        return False
    vco = visual.setdefault("visualContainerObjects", {})
    entries = vco.setdefault(obj_name, [{"properties": {}}])
    target = next((e for e in entries if "selector" not in e), None)
    if target is None:
        target = {"properties": {}}; entries.insert(0, target)
    target.setdefault("properties", {}).update(props)
    return True

changed = []
for path, data in walk_visuals("MyProject.Report"):
    vt = (data.get("visual") or {}).get("visualType", "")
    if vt in DECORATIVE:
        continue
    if set_vc_object(data, "title", {
            "fontSize": num(14), "fontFamily": text("Segoe UI Semibold"),
            "fontColor": color("#252423")}):
        save(path, data); changed.append(path)
print(f"updated {len(changed)} visuals")
```

Merging (not replacing) preserves per-visual `text` overrides and scoped entries.

## Pattern: hide all visual-level filter cards

```python
for path, data in walk_visuals(report):
    fc = data.get("filterConfig", {})
    dirty = False
    for flt in fc.get("filters", []):
        if not flt.get("isHiddenInViewMode"):
            flt["isHiddenInViewMode"] = True; dirty = True
    if dirty: save(path, data)
```

## Pattern: retarget a renamed field everywhere

Renamed `Sales[Amount]` → `Sales[Net Amount]` in the model; fix report references:

```python
def rename_refs(node, entity, old, new):
    """Recursively fix Property refs for a given Entity in any PBIR JSON."""
    hits = 0
    if isinstance(node, dict):
        for kind in ("Column", "Measure", "HierarchyLevel"):
            k = node.get(kind)
            if isinstance(k, dict) and k.get("Property") == old:
                src = k.get("Expression", {}).get("SourceRef", {})
                if src.get("Entity") == entity:
                    k["Property"] = new; hits += 1
        for v in node.values(): hits += rename_refs(v, entity, old, new)
    elif isinstance(node, list):
        for v in node: hits += rename_refs(v, entity, old, new)
    return hits
```

Also update string-based refs consistently: `queryRef` (`"Sales.Amount"` → `"Sales.Net Amount"`) **and every selector `metadata`, `sortDefinition`, `columnWidth`, `columnFormatting` entry using that queryRef**. Run rename over: all `visual.json`, `page.json`, `report.json`, `bookmarks/*.json`, `reportExtensions.json`.

## Pattern: TMDL batch format-string change

Line-based editing that preserves everything else byte-for-byte:

```python
import re, glob

PATTERN = re.compile(r"^(\t+)formatString: .*$")

def set_format_for_measures(tmdl_path, measure_names, new_fmt):
    with open(tmdl_path, encoding="utf-8") as f:
        lines = f.readlines()
    out, current, in_target = [], None, False
    for line in lines:
        m = re.match(r"^\tmeasure (?:'([^']+)'|(\S+))", line)
        if m:
            current = m.group(1) or m.group(2)
            in_target = current in measure_names
        if in_target and PATTERN.match(line):
            line = PATTERN.sub(rf"\1formatString: {new_fmt}", line)
        out.append(line)
    with open(tmdl_path, "w", encoding="utf-8", newline="") as f:
        f.writelines(out)
```

For structural TMDL edits (adding measures/properties), insert whole tab-indented blocks at the right position rather than rewriting the file model — TMDL has no reliable Python parser here.

## Validation pass (always run after batch edits)

```python
import json, glob, subprocess, sys

errs = []
for p in glob.glob("**/definition/**/*.json", recursive=True):
    try: json.load(open(p, encoding="utf-8"))
    except Exception as e: errs.append(f"{p}: {e}")

# TMDL sanity: tabs only, no duplicate property on same object depth
for p in glob.glob("**/definition/**/*.tmdl", recursive=True):
    for i, line in enumerate(open(p, encoding="utf-8"), 1):
        if line.startswith(" ") and line.strip():
            errs.append(f"{p}:{i}: space indentation (must be tabs)")

print("\n".join(errs) or "all files valid")
sys.exit(1 if errs else 0)
```

Additional checks for PBIR:
- Every `"Value"` literal matches `^('.*'|-?\d+(\.\d+)?[DL]|true|false|null)$`.
- Selectors' `metadata` values exist among the visual's `queryRef`s.
- No visual.json got a property outside the schema (compare keys against a known-good sibling if in doubt).

## Multi-report batching

The same walker applies across repos of reports: glob `*/ *.Report/definition/...`. Idempotency matters — write scripts so a second run is a no-op (check-before-set), enabling safe re-runs in CI.
