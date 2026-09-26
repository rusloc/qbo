"""qbo.sync_state access (spec §2.3): one row per entity, written through the run's connection.

`watermark` is the QBO server time at which the entity was last read completely (backfill or
cdc). The next cdc asks for changes since watermark - 10 minutes. A failed or refused run keeps
the old watermark (coalesce) and only updates last_status / last_run / rows_upserted.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

BACKFILL_OK = "backfill_ok"
CDC_OK = "cdc_ok"
CDC_CAP_BACKFILL = "cdc_cap_backfill"  # CDC hit the 1000-object cap; entity re-read in full
NOT_BACKFILLED = "not_backfilled"  # cdc refused: no watermark yet
GAP_REFUSED = "gap_refused"  # cdc refused: watermark older than the 30-day CDC window
ERROR = "error"

SELECT_SQL = """
select
     s.entity_type                 _entity_type
    ,s.watermark                   _watermark
    ,s.last_status                 _last_status
    ,s.last_run                    _last_run
    ,s.rows_upserted               _rows_upserted
from qbo.sync_state s
order by s.entity_type
"""

UPSERT_SQL = """
insert into qbo.sync_state (
     entity_type
    ,watermark
    ,last_status
    ,last_run
    ,rows_upserted
)
values (%s, %s, %s, %s, %s)
on conflict (entity_type) do update
set
     watermark     = coalesce(excluded.watermark, sync_state.watermark)
    ,last_status   = excluded.last_status
    ,last_run      = excluded.last_run
    ,rows_upserted = excluded.rows_upserted
"""


@dataclass(frozen=True)
class EntityState:
    entity_type: str
    watermark: datetime | None
    last_status: str | None
    last_run: datetime | None
    rows_upserted: int | None


def read_all(conn: Any) -> dict[str, EntityState]:
    rows = conn.execute(SELECT_SQL).fetchall()
    return {row[0]: EntityState(*row) for row in rows}


def write(
    conn: Any,
    entity: str,
    *,
    watermark: datetime | None,
    status: str,
    run_at: datetime,
    rows: int,
) -> None:
    """Upsert the entity's row. watermark=None keeps the stored one. The caller commits."""
    conn.execute(UPSERT_SQL, (entity, watermark, status, run_at, rows))


def rollback_quietly(conn: Any) -> None:
    """Roll back after a failure; a failing rollback must not hide the original error."""
    with contextlib.suppress(Exception):
        conn.rollback()
