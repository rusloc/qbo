"""`qbo_sync backfill [entity...]`: full re-read of entities into qbo.raw_entity (spec §1, §4 P1).

Per entity: `select * from <Entity> [where Active in (true, false)] orderby Id
startposition n maxresults 1000`, pages until one returns fewer than 1000 rows. Each page's raw
response text is landed unchanged with one synced_at per entity run (raw is insert-only; a
re-run adds a new snapshot, and dbt keeps the latest row per id). The watermark is the QBO
server time of the first page, so the next cdc (watermark - 10 min) covers every change made
while the pages were read. Pages + sync_state commit together per entity.

After paging, `select count(*)` is compared with the rows fetched (spec §4 gate P1) and logged;
a mismatch is a warning (objects can be created mid-run), not a failure.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from qbo_sync import state
from qbo_sync.client import (
    MAX_RESULTS,
    QboApiError,
    QboClient,
    parse,
    server_time,
    utcnow,
)
from qbo_sync.entities import NAME_LISTS
from qbo_sync.jsonlog import log

# db.land_raw(conn, entity_type, doc, path, synced_at) -> inserted rows (ferry-A's contract)
Land = Callable[[Any, str, str, Sequence[str], datetime], int]


def _where(entity: str) -> str:
    return " where Active in (true, false)" if entity in NAME_LISTS else ""


def page_statement(entity: str, start_position: int) -> str:
    return (
        f"select * from {entity}{_where(entity)} orderby Id "
        f"startposition {start_position} maxresults {MAX_RESULTS}"
    )


def count_statement(entity: str) -> str:
    return f"select count(*) from {entity}{_where(entity)}"


def _api_count(client: QboClient, entity: str) -> int | None:
    try:
        value = parse(client.query(count_statement(entity))).get("QueryResponse", {})
    except QboApiError as err:
        log("api_count_unavailable", "warning", entity=entity, error=str(err))
        return None
    count = value.get("totalCount")
    return count if isinstance(count, int) else None


def backfill_entity(
    conn: Any,
    client: QboClient,
    entity: str,
    *,
    land: Land,
    now: Callable[[], datetime] = utcnow,
    status: str = state.BACKFILL_OK,
) -> int:
    """Read every object of `entity`, land the pages, set the watermark, commit. Returns rows landed."""
    synced_at = now()
    watermark: datetime | None = None
    fetched = 0
    landed = 0
    start_position = 1
    while True:
        text = client.query(page_statement(entity, start_position))
        doc = parse(text)
        if watermark is None:
            watermark = server_time(doc) or synced_at
        rows = len(doc.get("QueryResponse", {}).get(entity, []))
        if rows:
            landed += land(conn, entity, text, ("QueryResponse", entity), synced_at)
        fetched += rows
        log("page_landed", entity=entity, start_position=start_position, rows=rows)
        if rows < MAX_RESULTS:
            break
        start_position += MAX_RESULTS
    api_count = _api_count(client, entity)
    log(
        "backfill_entity_done",
        "info" if api_count in (None, fetched) else "warning",
        entity=entity,
        rows_fetched=fetched,
        rows_landed=landed,
        api_count=api_count,
        watermark=watermark,
    )
    state.write(conn, entity, watermark=watermark, status=status, run_at=synced_at, rows=landed)
    conn.commit()
    return landed


def run(
    conn: Any,
    client: QboClient,
    entities: Sequence[str],
    *,
    land: Land,
    now: Callable[[], datetime] = utcnow,
) -> int:
    """Backfill each entity; an API failure on one entity does not stop the others. Exit code."""
    failed: list[str] = []
    for entity in entities:
        try:
            backfill_entity(conn, client, entity, land=land, now=now)
        except QboApiError as err:
            state.rollback_quietly(conn)
            state.write(conn, entity, watermark=None, status=state.ERROR, run_at=now(), rows=0)
            conn.commit()
            log("entity_failed", "error", entity=entity, error=str(err))
            failed.append(entity)
    log(
        "backfill_done",
        "error" if failed else "info",
        entities_ok=[e for e in entities if e not in failed],
        entities_failed=failed,
    )
    return 1 if failed else 0
