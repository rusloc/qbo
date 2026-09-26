"""Land the synthetic demo dataset (demo_data/*.json) into qbo.raw_entity.

Each file holds one JSON array of QBO objects; the file stem is the QBO entity type. Every file
goes through the same ``qbo_sync.db.land_raw`` path as the real extractor, with one fixed
``synced_at`` so a re-run inserts 0 rows (raw PK: entity_type, qbo_id, synced_at). One commit
at the end: all files land, or none do.

Usage (from the repo root):
    etl/.venv/Scripts/python etl/load_demo.py --dry-run   # count only, no database
    etl/.venv/Scripts/python etl/load_demo.py             # needs DB_URL (etl/.env), writes to qbo
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from qbo_sync.config import ConfigError, load_settings
from qbo_sync.db import connect, land_raw

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo_data"
# Fixed load time for the demo (after the data window 2024-09..2026-08). Real syncs land later,
# so their versions win in stg_entity_latest; see the hand-off note on mixing demo and real data.
DEMO_SYNCED_AT = datetime(2026, 9, 1, tzinfo=UTC)


def demo_files(folder: Path) -> list[Path]:
    files = sorted(folder.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no *.json files in {folder}; run generate_synthetic.py first")
    return files


def count_elements(path: Path) -> int:
    """Top-level array length, counted without parsing numbers (no float, no Decimal needed)."""
    return len(json.loads(path.read_text(encoding="utf-8"), parse_float=str, parse_int=str))


def load(conn, files: list[Path]) -> dict[str, int]:
    inserted = {}
    for path in files:
        inserted[path.stem] = land_raw(conn, path.stem, path.read_text(encoding="utf-8"), (), DEMO_SYNCED_AT)
    return inserted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Land demo_data/*.json into qbo.raw_entity.")
    parser.add_argument("--dir", type=Path, default=DEMO_DIR, help="folder with <Entity>.json files")
    parser.add_argument("--dry-run", action="store_true", help="count the files' objects; no database")
    args = parser.parse_args(argv)

    files = demo_files(args.dir)
    if args.dry_run:
        total = 0
        for path in files:
            n = count_elements(path)
            total += n
            print(f"{path.stem:<14} {n:>6} objects")
        print(f"{'total':<14} {total:>6} objects (dry run, nothing written)")
        return 0

    try:
        settings = load_settings("db_url")
    except ConfigError as err:
        print(f"config error: {err}", file=sys.stderr)
        return 2
    with connect(settings) as conn:
        inserted = load(conn, files)
        conn.commit()
    for entity, n in inserted.items():
        print(f"{entity:<14} {n:>6} rows inserted")
    print(f"{'total':<14} {sum(inserted.values()):>6} rows inserted (synced_at {DEMO_SYNCED_AT.isoformat()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
