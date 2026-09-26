"""qbo_sync.status and qbo_sync.state: sync_state read-out, CDC window, token presence only."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from qbo_sync import state, status

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


class FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows

    def fetchall(self) -> list[tuple]:
        return self.rows

    def fetchone(self) -> tuple | None:
        return self.rows[0] if self.rows else None


class FakeConn:
    def __init__(self, rows: list[tuple], has_token: bool) -> None:
        self.rows = rows
        self.has_token = has_token
        self.sql: list[str] = []
        self.params: list[tuple] = []
        self.events: list[str] = []

    def execute(self, sql: str, params: tuple = ()) -> FakeCursor:
        self.sql.append(sql)
        self.params.append(params)
        if "from qbo.sync_state" in sql:
            return FakeCursor(self.rows)
        if "refresh_token_lock() is not null" in sql:
            self.events.append("token_check")
            return FakeCursor([(self.has_token,)])
        return FakeCursor([])

    def rollback(self) -> None:
        self.events.append("rollback")

    def commit(self) -> None:
        self.events.append("commit")


def lines(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_status_reports_watermarks_and_days_left_in_the_cdc_window(capsys) -> None:
    rows = [
        ("Invoice", NOW - timedelta(days=1), state.CDC_OK, NOW - timedelta(days=1), 3),
        ("Bill", NOW - timedelta(days=31), state.BACKFILL_OK, NOW - timedelta(days=31), 7),
    ]
    conn = FakeConn(rows, has_token=True)
    assert status.run(conn, ["Invoice", "Bill", "Class"], now=lambda: NOW) == 0
    assert conn.events == ["token_check", "rollback"]  # rollback releases the advisory lock
    out = lines(capsys)
    by_entity = {line["entity"]: line for line in out if line["event"] == "entity_status"}
    assert by_entity["Invoice"]["cdc_days_left"] == 29.0
    assert by_entity["Bill"]["cdc_days_left"] < 0
    assert by_entity["Class"]["watermark"] is None
    summary = next(line for line in out if line["event"] == "status_summary")
    assert summary["refresh_token_stored"] is True
    assert summary["entities_never_backfilled"] == ["Class"]
    assert summary["entities_past_cdc_window"] == ["Bill"]
    assert summary["next_step"] == "python -m qbo_sync backfill Class Bill"
    assert summary["level"] == "warning"


def test_status_without_a_stored_token_points_to_auth(capsys) -> None:
    assert status.run(FakeConn([], has_token=False), ["Invoice"], now=lambda: NOW) == 0
    summary = next(line for line in lines(capsys) if line["event"] == "status_summary")
    assert summary["refresh_token_stored"] is False
    assert summary["next_step"] == "python -m qbo_sync auth"


def test_status_all_fresh_points_to_cdc(capsys) -> None:
    rows = [("Invoice", NOW - timedelta(hours=20), state.CDC_OK, NOW, 0)]
    status.run(FakeConn(rows, has_token=True), ["Invoice"], now=lambda: NOW)
    summary = next(line for line in lines(capsys) if line["event"] == "status_summary")
    assert summary["next_step"] == "python -m qbo_sync cdc" and summary["level"] == "info"


def test_token_check_never_selects_the_token_itself() -> None:
    assert "is not null" in status.TOKEN_PRESENT_SQL


def test_state_write_keeps_the_old_watermark_when_none_is_given() -> None:
    conn = FakeConn([], has_token=True)
    state.write(conn, "Invoice", watermark=None, status=state.ERROR, run_at=NOW, rows=0)
    assert "coalesce(excluded.watermark, sync_state.watermark)" in conn.sql[0]
    assert conn.params[0] == ("Invoice", None, state.ERROR, NOW, 0)


def test_state_read_all_maps_rows_by_entity() -> None:
    rows = [("Invoice", NOW, state.CDC_OK, NOW, 5)]
    got = state.read_all(FakeConn(rows, has_token=True))
    assert got["Invoice"].watermark == NOW and got["Invoice"].rows_upserted == 5
