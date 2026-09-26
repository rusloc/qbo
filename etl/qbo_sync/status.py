"""`qbo_sync status`: per-entity sync_state and how many days remain in the CDC window.

Needs only DB_URL. Whether a refresh token is stored is checked inside Postgres
(`refresh_token_lock() is not null`), so the token itself never leaves the database; the
rollback right after releases the advisory lock.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from qbo_sync import state
from qbo_sync.cdc import MAX_LOOKBACK, OVERLAP
from qbo_sync.client import utcnow
from qbo_sync.jsonlog import log

TOKEN_PRESENT_SQL = """
select
     qbo.refresh_token_lock() is not null  _has_refresh_token
"""


def run(conn: Any, entities: Sequence[str], *, now: Callable[[], datetime] = utcnow) -> int:
    states = state.read_all(conn)
    row = conn.execute(TOKEN_PRESENT_SQL).fetchone()
    conn.rollback()
    has_token = bool(row and row[0])
    at = now()
    never: list[str] = []
    past_window: list[str] = []
    names = list(entities) + sorted(set(states) - set(entities))
    for entity in names:
        current = states.get(entity)
        days_left: float | None = None
        if current is None or current.watermark is None:
            never.append(entity)
        else:
            remaining = MAX_LOOKBACK - OVERLAP - (at - current.watermark)
            days_left = round(remaining.total_seconds() / 86400, 1)
            if days_left < 0:
                past_window.append(entity)
        log(
            "entity_status",
            entity=entity,
            watermark=current.watermark if current else None,
            last_status=current.last_status if current else None,
            last_run=current.last_run if current else None,
            rows_upserted=current.rows_upserted if current else None,
            cdc_days_left=days_left,
        )
    log(
        "status_summary",
        "info" if has_token and not never and not past_window else "warning",
        refresh_token_stored=has_token,
        entities_never_backfilled=never,
        entities_past_cdc_window=past_window,
        next_step=_next_step(has_token, never + past_window, entities),
    )
    return 0


def _next_step(has_token: bool, stale: list[str], entities: Sequence[str]) -> str:
    if not has_token:
        return "python -m qbo_sync auth"
    if set(stale) >= set(entities):
        return "python -m qbo_sync backfill"
    if stale:
        return f"python -m qbo_sync backfill {' '.join(stale)}"
    return "python -m qbo_sync cdc"
