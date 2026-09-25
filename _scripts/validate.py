#!/usr/bin/env python3
"""Repo validator for a PBIP report stack.

Three checks, as required by CLAUDE.md > Verification:

  1. JSON parse    — every .json / .pbir / .pbip / .pbism parses (BOM tolerated).
  2. Encoding      — every text file decodes as UTF-8 and carries no mojibake
                     markers (the symptom of a round-trip through a non-UTF-8 editor).
  3. TMDL tabs     — every .tmdl file indents with tabs, never spaces.

Usage:
    python _scripts/validate.py            # validate the whole repo
    python _scripts/validate.py ABC XYZ   # validate only these paths

Exit code 0 = green, 1 = at least one failure (each named with its file).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories never worth validating: git internals and PBIX backups.
# `.pbi/` is NOT skipped — its *.json files are tracked (only cache.abf is
# gitignored, and .abf is binary so no check picks it up anyway).
SKIP_DIRS = {".git", "__backup__", "__pycache__", ".log"}

JSON_SUFFIXES = {".json", ".pbir", ".pbip", ".pbism"}
TEXT_SUFFIXES = JSON_SUFFIXES | {".tmdl", ".dax", ".md"}

# Byte sequences that mean UTF-8 was read as cp1252 somewhere upstream.
MOJIBAKE_MARKERS = ("Ã¢", "Ã©", "Ã¼", "â€œ", "â€™", "â€“", "Ð", "Â ", "Â«")


def walk(targets: list[Path]):
    """Yield every file under targets, skipping SKIP_DIRS at any depth."""
    for target in targets:
        if target.is_file():
            yield target
            continue
        for path in target.rglob("*"):
            if not path.is_file():
                continue
            if SKIP_DIRS.intersection(path.relative_to(target).parts):
                continue
            yield path


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def check_json(path: Path, failures: list[str]) -> None:
    try:
        # utf-8-sig strips the BOM Power BI Desktop writes on some files.
        with path.open(encoding="utf-8-sig") as fh:
            json.load(fh)
    except json.JSONDecodeError as exc:
        failures.append(f"{rel(path)}:{exc.lineno}:{exc.colno}  invalid JSON — {exc.msg}")
    except UnicodeDecodeError as exc:
        failures.append(f"{rel(path)}  not valid UTF-8 — {exc.reason} at byte {exc.start}")


def check_encoding(path: Path, failures: list[str]) -> None:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        failures.append(f"{rel(path)}  not valid UTF-8 — {exc.reason} at byte {exc.start}")
        return
    for lineno, line in enumerate(text.splitlines(), 1):
        for marker in MOJIBAKE_MARKERS:
            if marker in line:
                failures.append(f"{rel(path)}:{lineno}  mojibake {marker!r} — re-save as UTF-8")
                return


def check_tmdl_tabs(path: Path, failures: list[str]) -> None:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return  # already reported by check_encoding
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.startswith(" ") and line.strip():
            failures.append(f"{rel(path)}:{lineno}  space indent in TMDL — must be tabs")
            return


def main(argv: list[str]) -> int:
    # Windows consoles default to cp1252 and would mangle or raise on the
    # non-ASCII markers a failure message can carry.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    targets = [Path(a).resolve() for a in argv[1:]] or [REPO_ROOT]
    for target in targets:
        if not target.exists():
            print(f"FAIL  no such path: {target}")
            return 1

    json_files: list[Path] = []
    tmdl_files: list[Path] = []
    text_files: list[Path] = []
    for path in walk(targets):
        suffix = path.suffix.lower()
        if suffix in JSON_SUFFIXES:
            json_files.append(path)
        if suffix == ".tmdl":
            tmdl_files.append(path)
        if suffix in TEXT_SUFFIXES:
            text_files.append(path)

    json_failures: list[str] = []
    encoding_failures: list[str] = []
    tmdl_failures: list[str] = []

    for path in json_files:
        check_json(path, json_failures)
    for path in text_files:
        check_encoding(path, encoding_failures)
    for path in tmdl_files:
        check_tmdl_tabs(path, tmdl_failures)

    checks = (
        ("JSON parse", len(json_files), json_failures),
        ("encoding", len(text_files), encoding_failures),
        ("TMDL tabs", len(tmdl_files), tmdl_failures),
    )

    total = 0
    for label, count, failures in checks:
        status = "OK  " if not failures else "FAIL"
        print(f"{status}  {label:<11} {count:>4} file(s), {len(failures)} problem(s)")
        for failure in failures:
            print(f"        {failure}")
        total += len(failures)

    print("-" * 56)
    print("GREEN — validate.py passed" if not total else f"RED — {total} problem(s)")
    return 0 if not total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
