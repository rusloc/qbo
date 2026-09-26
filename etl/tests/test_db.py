"""land_raw / connect against a fake connection: there is no database in unit tests."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from qbo_sync import db
from qbo_sync.config import ConfigError, Settings

SYNCED_AT = datetime(2026, 9, 1, tzinfo=UTC)


class FakeCursor:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount
        self.calls: list[tuple[str, dict]] = []

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, rowcount: int = 3):
        self.cur = FakeCursor(rowcount)
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1


def settings(db_url):
    return Settings(db_url, None, None, None, None)


def test_land_raw_sql_parses_json_in_postgres():
    sql = " ".join(db.LAND_RAW_SQL.split())
    assert "insert into qbo.raw_entity (" in sql
    assert "jsonb_array_elements(%(doc)s::jsonb #> %(path)s::text[]) e(elem)" in sql
    assert "e.elem ->> 'Id'" in sql
    assert sql.endswith("on conflict do nothing")


def test_land_raw_passes_text_and_path_unparsed():
    conn = FakeConn(rowcount=2)
    # Not even valid JSON for Python: proves land_raw never parses the document itself.
    doc = '{"QueryResponse": {"Invoice": [{"Id": "1", "TotalAmt": 0.1}, {"Id": "2"}]'
    n = db.land_raw(conn, "Invoice", doc, ("QueryResponse", "Invoice"), SYNCED_AT)
    assert n == 2
    [(sql, params)] = conn.cur.calls
    assert sql == db.LAND_RAW_SQL
    assert params == {
        "entity_type": "Invoice",
        "doc": doc,
        "path": ["QueryResponse", "Invoice"],
        "synced_at": SYNCED_AT,
    }
    assert conn.commits == 0  # the caller commits


def test_land_raw_empty_path_means_doc_is_the_array():
    conn = FakeConn()
    db.land_raw(conn, "Account", '[{"Id": "1"}]', (), SYNCED_AT)
    assert conn.cur.calls[0][1]["path"] == []


def test_land_raw_rejects_naive_timestamp_and_non_text():
    conn = FakeConn()
    with pytest.raises(ValueError):
        db.land_raw(conn, "Account", "[]", (), datetime(2026, 9, 1))  # noqa: DTZ001 (naive on purpose)
    with pytest.raises(TypeError):
        db.land_raw(conn, "Account", b"[]", (), SYNCED_AT)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        db.land_raw(conn, "Account", "[]", "QueryResponse", SYNCED_AT)
    assert conn.cur.calls == []


def test_land_raw_accepts_non_utc_aware_timestamp():
    conn = FakeConn()
    local = datetime(2026, 9, 1, 2, tzinfo=timezone(timedelta(hours=2)))
    db.land_raw(conn, "Account", "[]", (), local)
    assert conn.cur.calls[0][1]["synced_at"] == local


def test_connect_defaults(monkeypatch):
    captured = {}

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return "conn"

    monkeypatch.setattr(db.psycopg, "connect", fake_connect)
    conn = db.connect(settings("postgresql://qbo_etl.ref:p%40ss@pooler.example.com:5432/postgres"))
    assert conn == "conn"
    assert captured["autocommit"] is False
    assert captured["prepare_threshold"] is None
    assert captured["sslmode"] == "require"
    assert captured["application_name"] == "qbo_sync"
    assert captured["user"] == "qbo_etl.ref"
    assert captured["password"] == "p@ss"
    assert captured["dbname"] == "postgres"


def test_connect_keeps_explicit_sslmode(monkeypatch):
    captured = {}
    monkeypatch.setattr(db.psycopg, "connect", lambda **kw: captured.update(kw))
    db.connect(settings("postgresql://u:p@h/db?sslmode=verify-full"))
    assert captured["sslmode"] == "verify-full"


def test_connect_errors_never_echo_the_url():
    with pytest.raises(ConfigError, match="missing: DB_URL"):
        db.connect(settings(None))
    secret_url = "host=h password=s3cr3t = broken"
    with pytest.raises(ConfigError) as err:
        db.connect(settings(secret_url))
    assert "s3cr3t" not in str(err.value)
    assert err.value.__cause__ is None
