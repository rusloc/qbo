"""`qbo_sync cdc`: daily incremental landing through QBO change data capture (spec §1, ADR-0004).

Per entity (one entity per CDC request, so the object cap is unambiguous):
- no watermark -> refused (`not_backfilled`): run backfill first;
- changedSince = watermark - 10 min; if that is more than 30 days ago -> refused
  (`gap_refused`) with the exact re-backfill command. Nothing is called for that entity;
- otherwise GET /cdc, land the raw response text unchanged, including `status: "Deleted"`
  stubs (dbt flags is_deleted from them), and move the watermark to the response's server time.
- Intuit caps a CDC response at 1000 objects. At the cap the response may be truncated, so
  the entity is re-read in full (backfill) in the same run and marked `cdc_cap_backfill`.
  Deletes cut off by the cap cannot be recovered from the API; this is logged as a warning.
Exit code 1 if any entity failed or was refused; the other entities still run.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from qbo_sync import backfill, state
from qbo_sync.client import QboApiError, QboClient, parse, server_time, utcnow
from qbo_sync.jsonlog import log

OVERLAP = timedelta(minutes=10)
MAX_LOOKBACK = timedelta(days=30)
CDC_OBJECT_CAP = 1000


def entity_arrays(
    doc: Mapping[str, Any], entity: str
) -> Iterator[tuple[tuple[str, ...], list[Any]]]:
    """Yield (land_raw path, objects) for every `entity` array inside a CDC response."""
    for c_index, part in enumerate(doc.get("CDCResponse") or []):
        for q_index, query_response in enumerate(part.get("QueryResponse") or []):
            objects = query_response.get(entity)
            if objects:
                path = ("CDCResponse", str(c_index), "QueryResponse", str(q_index), entity)
                yield path, objects


def cdc_entity(
    conn: Any,
    client: QboClient,
    entity: str,
    changed_since: datetime,
    *,
    land: backfill.Land,
    now: Callable[[], datetime] = utcnow,
) -> int:
    """One CDC call for one entity; lands, moves the watermark, commits. Returns rows landed."""
    synced_at = now()
    text = client.cdc([entity], changed_since)
    doc = parse(text)
    objects = 0
    deleted = 0
    landed = 0
    for path, items in entity_arrays(doc, entity):
        objects += len(items)
        deleted += sum(1 for i in items if isinstance(i, dict) and i.get("status") == "Deleted")
        landed += land(conn, entity, text, path, synced_at)
    if objects >= CDC_OBJECT_CAP:
        conn.commit()  # keep what CDC returned, Deleted stubs included
        log(
            "cdc_cap_reached",
            "warning",
            entity=entity,
            objects=objects,
            cap=CDC_OBJECT_CAP,
            action="full re-read of the entity; deletes beyond the cap may be missing",
        )
        return landed + backfill.backfill_entity(
            conn, client, entity, land=land, now=now, status=state.CDC_CAP_BACKFILL
        )
    watermark = server_time(doc) or synced_at
    state.write(conn, entity, watermark=watermark, status=state.CDC_OK, run_at=synced_at, rows=landed)
    conn.commit()
    log(
        "cdc_entity_done",
        entity=entity,
        changed_since=changed_since,
        objects=objects,
        deleted=deleted,
        rows_landed=landed,
        watermark=watermark,
    )
    return landed


def run(
    conn: Any,
    client: QboClient,
    entities: Sequence[str],
    *,
    land: backfill.Land,
    now: Callable[[], datetime] = utcnow,
) -> int:
    states = state.read_all(conn)
    conn.rollback()  # end the read-only transaction
    refused: list[str] = []
    failed: list[str] = []
    for entity in entities:
        run_at = now()
        current = states.get(entity)
        if current is None or current.watermark is None:
            state.write(conn, entity, watermark=None, status=state.NOT_BACKFILLED, run_at=run_at, rows=0)
            conn.commit()
            log("cdc_refused_not_backfilled", "error", entity=entity)
            refused.append(entity)
            continue
        changed_since = current.watermark - OVERLAP
        if run_at - changed_since > MAX_LOOKBACK:
            state.write(conn, entity, watermark=None, status=state.GAP_REFUSED, run_at=run_at, rows=0)
            conn.commit()
            log(
                "cdc_refused_gap",
                "error",
                entity=entity,
                watermark=current.watermark,
                gap_days=round((run_at - changed_since).total_seconds() / 86400, 1),
                max_days=MAX_LOOKBACK.days,
            )
            refused.append(entity)
            continue
        try:
            cdc_entity(conn, client, entity, changed_since, land=land, now=now)
        except QboApiError as err:
            state.rollback_quietly(conn)
            state.write(conn, entity, watermark=None, status=state.ERROR, run_at=now(), rows=0)
            conn.commit()
            log("entity_failed", "error", entity=entity, error=str(err))
            failed.append(entity)
    if refused:
        command = f"python -m qbo_sync backfill {' '.join(refused)}"
        log(
            "cdc_refused",
            "error",
            entities=refused,
            message=(
                "CDC only reaches 30 days back (and needs a first backfill); "
                f"re-backfill these entities, then cdc resumes: {command}"
            ),
            command=command,
        )
    log(
        "cdc_done",
        "error" if refused or failed else "info",
        entities_ok=[e for e in entities if e not in refused and e not in failed],
        entities_refused=refused,
        entities_failed=failed,
    )
    return 1 if refused or failed else 0
