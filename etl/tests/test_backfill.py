"""qbo_sync.backfill: ORDERBY Id paging stops right, raw text lands unchanged, per-entity commit."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qbo_sync import backfill, state
from qbo_sync.client import QboApiError, parse

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "qbo_api"
NOW = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)
SERVER_TIME = "2026-09-26T08:00:00.123-07:00"


def page(entity: str, rows: int, first_id: int = 1) -> str:
    objects = [
        {"domain": "QBO", "Id": str(i), "SyncToken": "0", "TotalAmt": 10.10}
        for i in range(first_id, first_id + rows)
    ]
    query_response = {entity: objects, "startPosition": first_id, "maxResults": rows} if rows else {}
    return json.dumps({"QueryResponse": query_response, "time": SERVER_TIME})


def count_response(total: int) -> str:
    return json.dumps({"QueryResponse": {"totalCount": total}, "time": SERVER_TIME})


class FakeClient:
    """Pages are served in order; `select count(*)` answers from `counts`; `fail` raises."""

    def __init__(self, pages: dict[str, list[str]], counts: dict[str, int], fail=()) -> None:
        self.pages = {k: list(v) for k, v in pages.items()}
        self.counts = counts
        self.fail = set(fail)
        self.statements: list[str] = []

    def query(self, statement: str) -> str:
        self.statements.append(statement)
        entity = statement.split(" from ")[1].split()[0]
        if entity in self.fail:
            raise QboApiError("query: HTTP 500 after 5 retries", status=500)
        if "count(*)" in statement:
            return count_response(self.counts[entity])
        return self.pages[entity].pop(0)


class Recorder:
    """Fake connection + land_raw + state.write, all writing to one ordered event list."""

    def __init__(self) -> None:
        self.events: list[tuple] = []
        self.landed: list[tuple] = []
        self.states: list[dict] = []

    def land(self, conn, entity, doc, path, synced_at):
        node = parse(doc)
        for key in path:
            node = node[int(key)] if isinstance(node, list) else node[key]
        self.landed.append((entity, doc, tuple(path), synced_at))
        self.events.append(("land", entity, len(node)))
        return len(node)

    def write_state(self, conn, entity, **kwargs):
        self.states.append({"entity": entity, **kwargs})
        self.events.append(("state", entity, kwargs["status"]))

    def commit(self) -> None:
        self.events.append(("commit",))

    def rollback(self) -> None:
        self.events.append(("rollback",))


@pytest.fixture
def rec(monkeypatch) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr(state, "write", recorder.write_state)
    return recorder


def run(rec: Recorder, client: FakeClient, entities: list[str]) -> int:
    return backfill.run(rec, client, entities, land=rec.land, now=lambda: NOW)


def test_pages_until_a_short_page_1000_1000_3(rec: Recorder) -> None:
    client = FakeClient(
        {"Invoice": [page("Invoice", 1000, 1), page("Invoice", 1000, 1001), page("Invoice", 3, 2001)]},
        {"Invoice": 2003},
    )
    assert run(rec, client, ["Invoice"]) == 0
    pages = [s for s in client.statements if "count(*)" not in s]
    assert pages == [
        "select * from Invoice orderby Id startposition 1 maxresults 1000",
        "select * from Invoice orderby Id startposition 1001 maxresults 1000",
        "select * from Invoice orderby Id startposition 2001 maxresults 1000",
    ]
    assert rec.events == [
        ("land", "Invoice", 1000),
        ("land", "Invoice", 1000),
        ("land", "Invoice", 3),
        ("state", "Invoice", state.BACKFILL_OK),
        ("commit",),
    ]
    assert rec.states[0]["rows"] == 2003
    assert rec.states[0]["watermark"] == datetime(2026, 9, 26, 15, 0, 0, 123000, tzinfo=UTC)
    assert rec.states[0]["run_at"] == NOW


def test_exactly_1000_rows_needs_one_empty_page_then_stops(rec: Recorder) -> None:
    client = FakeClient({"Vendor": [page("Vendor", 1000), page("Vendor", 0)]}, {"Vendor": 1000})
    assert run(rec, client, ["Vendor"]) == 0
    assert len([s for s in client.statements if "count(*)" not in s]) == 2
    assert [e for e in rec.events if e[0] == "land"] == [("land", "Vendor", 1000)]
    assert rec.states[0]["rows"] == 1000


def test_name_lists_include_inactive_objects_transactions_do_not_filter(rec: Recorder) -> None:
    client = FakeClient(
        {"Account": [page("Account", 2)], "Budget": [page("Budget", 1)]},
        {"Account": 2, "Budget": 1},
    )
    run(rec, client, ["Account", "Budget"])
    assert client.statements[0] == (
        "select * from Account where Active in (true, false) orderby Id "
        "startposition 1 maxresults 1000"
    )
    assert client.statements[1] == "select count(*) from Account where Active in (true, false)"
    assert client.statements[2] == "select * from Budget orderby Id startposition 1 maxresults 1000"


def test_raw_response_text_is_landed_unchanged_with_its_json_path(rec: Recorder) -> None:
    raw = (FIXTURES / "query_invoice_page.json").read_text(encoding="utf-8")
    client = FakeClient({"Invoice": [raw]}, {"Invoice": 2})
    run(rec, client, ["Invoice"])
    entity, doc, path, synced_at = rec.landed[0]
    assert (entity, path, synced_at) == ("Invoice", ("QueryResponse", "Invoice"), NOW)
    assert doc is raw  # never re-serialized: no float can sneak in


def test_budget_fixture_lands_through_the_same_path(rec: Recorder) -> None:
    raw = (FIXTURES / "query_budget_page.json").read_text(encoding="utf-8")
    client = FakeClient({"Budget": [raw]}, {"Budget": 1})
    assert run(rec, client, ["Budget"]) == 0
    assert rec.landed[0][2] == ("QueryResponse", "Budget")
    assert rec.states[0]["rows"] == 1


def test_count_mismatch_is_logged_as_warning(rec: Recorder, capsys) -> None:
    client = FakeClient({"Bill": [page("Bill", 2)]}, {"Bill": 3})
    assert run(rec, client, ["Bill"]) == 0
    done = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    done = next(d for d in done if d["event"] == "backfill_entity_done")
    assert (done["level"], done["rows_fetched"], done["api_count"]) == ("warning", 2, 3)


def test_failed_entity_rolls_back_is_recorded_and_others_continue(rec: Recorder) -> None:
    client = FakeClient({"Item": [page("Item", 1)]}, {"Item": 1}, fail={"Bill"})
    assert run(rec, client, ["Bill", "Item"]) == 1
    assert rec.events[:3] == [("rollback",), ("state", "Bill", state.ERROR), ("commit",)]
    assert rec.states[0]["watermark"] is None  # stored watermark kept (coalesce)
    assert ("state", "Item", state.BACKFILL_OK) in rec.events
