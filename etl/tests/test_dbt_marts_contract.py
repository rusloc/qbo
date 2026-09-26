"""Static ADR-0002 guard: dbt mart models vs the migration-owned tables (no database needed).

For every dbt/models/marts/<table>.sql, the final select must
- output only columns that exist in the migration DDL (dbt would otherwise ALTER TABLE ADD);
- never output an identity column (keys stay DB-generated);
- cast every varchar(n) target column to exactly varchar(n): dbt's incremental path widens a
  target column when the temp relation has a longer string type (text counts as 256), i.e. it
  would run ALTER TABLE on a migration-owned table.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "supabase" / "migrations"
MARTS = REPO / "dbt" / "models" / "marts"

TABLE = re.compile(r"create table qbo\.(\w+) \((.*?)\n\);", re.DOTALL)
COLUMN = re.compile(r"^\s*,?\s*(\w+)\s+(varchar\(\d+\)|integer|bigint|boolean|date|timestamptz|numeric\(\d+,\d+\)|jsonb)(.*)$")
SELECT_LINE = re.compile(r"^\s*,?\s*(.*?)\s{2,}(\w+)\s*$")


def migration_tables() -> dict[str, dict[str, tuple[str, bool]]]:
    tables: dict[str, dict[str, tuple[str, bool]]] = {}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        for name, body in TABLE.findall(path.read_text(encoding="utf-8")):
            cols = {}
            for line in body.splitlines():
                m = COLUMN.match(line)
                if m:
                    cols[m.group(1)] = (m.group(2), "generated always as identity" in m.group(3))
            tables[name] = cols
    return tables


def final_select(sql: str) -> dict[str, str]:
    """{output column: expression line} of the model's last top-level select."""
    lines = sql.splitlines()
    start = max(i for i, line in enumerate(lines) if line.rstrip() == "select")
    out: dict[str, str] = {}
    for line in lines[start + 1 :]:
        if line.startswith("from "):
            break
        m = SELECT_LINE.match(line)
        if m and m.group(1):
            out[m.group(2)] = m.group(1)
    return out


TABLES = migration_tables()
MODELS = sorted(p.stem for p in MARTS.glob("*.sql"))


def test_every_mart_model_fills_a_migration_table():
    assert MODELS, "no mart models found"
    assert set(MODELS) <= set(TABLES), f"mart models without a migration table: {set(MODELS) - set(TABLES)}"


@pytest.mark.parametrize("model", MODELS)
def test_mart_output_matches_migration(model):
    table = TABLES[model]
    output = final_select((MARTS / f"{model}.sql").read_text(encoding="utf-8"))
    assert output, f"{model}: final select not found"

    unknown = set(output) - set(table)
    assert not unknown, f"{model}: columns not in the table (dbt would ALTER TABLE): {unknown}"

    identity = [c for c in output if table[c][1]]
    assert not identity, f"{model}: writes identity column(s) {identity}"

    for column, expression in output.items():
        col_type = table[column][0]
        if col_type.startswith("varchar"):
            assert f"::{col_type}" in expression, f"{model}.{column}: cast to ::{col_type} missing"


def test_migration_parser_sees_the_identity_keys():
    assert TABLES["dim_account"]["account_key"] == ("integer", True)
    assert TABLES["fact_gl"]["gl_key"] == ("bigint", True)
    assert TABLES["dim_date"]["date_key"] == ("integer", False)
