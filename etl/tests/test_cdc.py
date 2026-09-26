"""qbo_sync.cdc: 30-day gap refusal, 10-minute overlap, Deleted stubs landed, 1000-object cap."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from qbo_sync import cdc, state
from qbo_sync.client import QboApiError, parse
from qbo_sync.state import EntityState

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "qbo_api"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
EMPTY_CDC = json.dumps(
    {"CDCResponse": [{"QueryResponse": [{}]}], "time": "2026-09-26T05:00:00.000-07:00"}
)


class FakeClient:
    def __init__(self, cdc_responses: dict[str, str], fail=(), pages=None) -> None:
        self.cdc_responses = cdc_responses
        self.fail = set(fail)
        self.pages = pages or {}
        self.cdc_calls: list[tuple[list[str], datetime]] = []
        self.statements: list[str] = []

    def cdc(self, entities, changed_since):
        self.cdc_calls.append((list(entities), changed_since))
        if entities[0] in self.fail:
            raise QboApiError("cdc: HTTP 503 after 5 retries", status=503)
        return self.cdc_responses[entities[0]]

    def query(self, statement: str) -> str:
        self.statements.append(statement)
        entity = statement.split(" from ")[1].split()[0]
        if "count(*)" in statement:
            return json.dumps({"QueryResponse": {"totalCount": 1}})
        return self.pages[entity].pop(0)


class Recorder:
    def __init__(self, states: dict[str, EntityState]) -> None:
        self.stored = states
        self.events: list[tuple] = []
        self.landed: list[tuple] = []
        self.states: list[dict] = []

    def land(self, conn, entity, doc, path, synced_at):
        node = parse(doc)
        for key in path:
            node = node[int(key)] if isinstance(node, list) else node[key]
        self.landed.append((entity, doc, tuple(path), synced_at, node))
        self.events.append(("land", entity, len(node)))
        return len(node)

    def read_all(self, conn):
        return self.stored

    def write_state(self, conn, entity, **kwargs):
        self.states.append({"entity": entity, **kwargs})
        self.events.append(("state", entity, kwargs["status"]))

    def commit(self) -> None:
        self.events.append(("commit",))

    def rollback(self) -> None:
        self.events.append(("rollback",))


def watermarked(**ages: timedelta) -> dict[str, EntityState]:
    return {
        entity: EntityState(entity, NOW - age, state.BACKFILL_OK, NOW - age, 1)
        for entity, age in ages.items()
    }


@pytest.fixture
def make(monkeypatch):
    def _make(states: dict[str, EntityState]) -> Recorder:
        recorder = Recorder(states)
        monkeypatch.setattr(state, "read_all", recorder.read_all)
        monkeypatch.setattr(state, "write", recorder.write_state)
        return recorder

    return _make


def run(rec: Recorder, client: FakeClient, entities: list[str]) -> int:
    return cdc.run(rec, client, entities, land=rec.land, now=lambda: NOW)


def test_gap_over_30_days_is_refused_without_calling_qbo(make, capsys) -> None:
    rec = make(watermarked(Invoice=timedelta(days=31), Bill=timedelta(hours=20)))
    client = FakeClient({"Bill": EMPTY_CDC})
    assert run(rec, client, ["Invoice", "Bill"]) == 1
    assert [call[0] for call in client.cdc_calls] == [["Bill"]]
    refused = next(s for s in rec.states if s["entity"] == "Invoice")
    assert refused["status"] == state.GAP_REFUSED and refused["watermark"] is None
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    summary = next(line for line in lines if line["event"] == "cdc_refused")
    assert summary["command"] == "python -m qbo_sync backfill Invoice"
    assert "30 days" in summary["message"]


def test_gap_boundary_counts_the_10_minute_overlap(make) -> None:
    inside = timedelta(days=30) - timedelta(minutes=11)  # changedSince 30d - 1 min ago
    outside = timedelta(days=30) - timedelta(minutes=9)  # changedSince 30d + 1 min ago
    rec = make(watermarked(Invoice=inside, Bill=outside))
    client = FakeClient({"Invoice": EMPTY_CDC})
    assert run(rec, client, ["Invoice", "Bill"]) == 1
    assert [call[0] for call in client.cdc_calls] == [["Invoice"]]
    assert ("state", "Bill", state.GAP_REFUSED) in rec.events


def test_entity_never_backfilled_is_refused(make) -> None:
    rec = make({})
    client = FakeClient({})
    assert run(rec, client, ["Class"]) == 1
    assert client.cdc_calls == []
    assert rec.states[0]["status"] == state.NOT_BACKFILLED


def test_changed_since_is_watermark_minus_10_minutes_one_entity_per_call(make) -> None:
    rec = make(watermarked(Invoice=timedelta(hours=24), Bill=timedelta(hours=23)))
    client = FakeClient({"Invoice": EMPTY_CDC, "Bill": EMPTY_CDC})
    assert run(rec, client, ["Invoice", "Bill"]) == 0
    assert client.cdc_calls == [
        (["Invoice"], NOW - timedelta(hours=24, minutes=10)),
        (["Bill"], NOW - timedelta(hours=23, minutes=10)),
    ]


def test_deleted_object_is_landed_and_watermark_moves_to_server_time(make, capsys) -> None:
    raw = (FIXTURES / "cdc_invoice_changed_and_deleted.json").read_text(encoding="utf-8")
    rec = make(watermarked(Invoice=timedelta(hours=24)))
    assert run(rec, FakeClient({"Invoice": raw}), ["Invoice"]) == 0
    _entity, doc, path, synced_at, objects = rec.landed[0]
    assert doc is raw
    assert path == ("CDCResponse", "0", "QueryResponse", "0", "Invoice")
    assert synced_at == NOW
    deleted = [o for o in objects if o.get("status") == "Deleted"]
    assert [o["Id"] for o in deleted] == ["9002"]
    assert rec.events == [("rollback",), ("land", "Invoice", 2), ("state", "Invoice", state.CDC_OK), ("commit",)]
    assert rec.states[0]["watermark"] == datetime(2026, 9, 25, 17, 0, 0, 456000, tzinfo=UTC)
    done = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    done = next(d for d in done if d["event"] == "cdc_entity_done")
    assert (done["objects"], done["deleted"]) == (2, 1)


def test_no_changes_lands_nothing_but_advances_the_watermark(make) -> None:
    rec = make(watermarked(Vendor=timedelta(days=2)))
    assert run(rec, FakeClient({"Vendor": EMPTY_CDC}), ["Vendor"]) == 0
    assert rec.landed == []
    assert rec.states[0]["watermark"] == datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def test_cap_of_1000_objects_triggers_a_full_re_read_of_that_entity(make) -> None:
    capped = json.dumps(
        {
            "CDCResponse": [
                {"QueryResponse": [{"Bill": [{"Id": str(i), "domain": "QBO"} for i in range(1000)]}]}
            ],
            "time": "2026-09-26T05:00:00.000-07:00",
        }
    )
    full_page = json.dumps({"QueryResponse": {"Bill": [{"Id": "1"}]}, "time": "2026-09-26T05:01:00-07:00"})
    rec = make(watermarked(Bill=timedelta(days=3)))
    client = FakeClient({"Bill": capped}, pages={"Bill": [full_page]})
    assert run(rec, client, ["Bill"]) == 0
    assert client.statements[0] == "select * from Bill orderby Id startposition 1 maxresults 1000"
    assert rec.events[1:] == [
        ("land", "Bill", 1000),
        ("commit",),  # CDC objects kept before the re-read
        ("land", "Bill", 1),
        ("state", "Bill", state.CDC_CAP_BACKFILL),
        ("commit",),
    ]
    assert rec.states[0]["watermark"] == datetime(2026, 9, 26, 12, 1, tzinfo=UTC)


def test_api_failure_on_one_entity_does_not_stop_the_others(make) -> None:
    rec = make(watermarked(Invoice=timedelta(hours=24), Bill=timedelta(hours=24)))
    client = FakeClient({"Bill": EMPTY_CDC}, fail={"Invoice"})
    assert run(rec, client, ["Invoice", "Bill"]) == 1
    assert ("state", "Invoice", state.ERROR) in rec.events
    assert ("state", "Bill", state.CDC_OK) in rec.events
