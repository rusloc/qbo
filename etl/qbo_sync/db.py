"""Database access for qbo_sync: connection factory and the raw-zone landing function.

Connects as ``qbo_etl`` (ADR-0003) with psycopg 3. ``land_raw`` hands the JSON text to Postgres
unparsed, so amounts go from the API body straight into ``jsonb`` (numeric) and never through a
Python float (spec 1, CLAUDE.md money rule).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import psycopg
from psycopg.conninfo import conninfo_to_dict

from qbo_sync.config import ConfigError, Settings

APPLICATION_NAME = "qbo_sync"
CONNECT_TIMEOUT_S = 15

# One qbo.raw_entity row per element of the array at `path` inside `doc`. Postgres parses the
# JSON; ON CONFLICT (entity_type, qbo_id, synced_at) DO NOTHING makes re-landing idempotent.
# A path that resolves to nothing (e.g. an empty QueryResponse page) inserts 0 rows.
LAND_RAW_SQL = """
insert into qbo.raw_entity (
     entity_type
    ,qbo_id
    ,payload
    ,synced_at
)
select
     %(entity_type)s::varchar(30)       _entity_type
    ,e.elem ->> 'Id'                    _qbo_id
    ,e.elem                             _payload
    ,%(synced_at)s::timestamptz         _synced_at
from jsonb_array_elements(%(doc)s::jsonb #> %(path)s::text[]) e(elem)
on conflict do nothing
"""


def connect(settings: Settings) -> psycopg.Connection:
    """Open a psycopg 3 connection from ``DB_URL`` (autocommit off; the caller commits).

    ``sslmode=require`` is added unless ``DB_URL`` sets its own sslmode. Automatic prepared
    statements are off so a transaction-mode pooler URL cannot break the run.
    """
    if not settings.db_url:
        raise ConfigError("missing: DB_URL")
    try:
        params = conninfo_to_dict(settings.db_url)
    except psycopg.Error:
        raise ConfigError("DB_URL cannot be parsed") from None  # the message could echo the URL

    params.setdefault("sslmode", "require")
    params.setdefault("application_name", APPLICATION_NAME)
    params.setdefault("connect_timeout", str(CONNECT_TIMEOUT_S))
    return psycopg.connect(**params, autocommit=False, prepare_threshold=None)


def land_raw(
    conn: psycopg.Connection,
    entity_type: str,
    doc: str,
    path: Sequence[str],
    synced_at: datetime,
) -> int:
    """Insert every entity of the JSON array at ``path`` in ``doc`` into ``qbo.raw_entity``.

    ``doc`` is JSON text (API response body or file contents); ``path`` is the key path to the
    array (``()`` when ``doc`` itself is the array; list indices as strings, e.g. ``'0'``).
    Returns the number of rows inserted (0 on an idempotent re-landing). The caller commits.
    """
    if not isinstance(doc, str):
        raise TypeError("doc must be JSON text (str); it is parsed by Postgres, not Python")
    if isinstance(path, str) or not all(isinstance(p, str) for p in path):
        raise TypeError("path must be a sequence of str")
    if synced_at.tzinfo is None or synced_at.utcoffset() is None:
        raise ValueError("synced_at must be timezone-aware")

    params = {
        "entity_type": entity_type,
        "doc": doc,
        "path": list(path),
        "synced_at": synced_at,
    }
    with conn.cursor() as cur:
        cur.execute(LAND_RAW_SQL, params)
        return cur.rowcount
