"""Structured JSON-lines logging to stdout (spec §4 Phase 1, ADR-0004).

Log lines name things, never values: no token, secret, auth code, state or realmId is ever
passed in. As a second guard, fields whose key names a secret are replaced by "[redacted]".
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from typing import Any

_REDACTED_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "client_id",
        "client_secret",
        "code",
        "auth_code",
        "state",
        "realm_id",
        "realmid",
        "authorization",
        "password",
        "db_url",
    }
)

_context: dict[str, Any] = {}


def bind(**fields: Any) -> None:
    """Add fields (run_id, command) to every later log line of this process."""
    _context.update(fields)


def _default(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)  # Decimal and anything else: exact text, never float


def log(event: str, level: str = "info", **fields: Any) -> None:
    """Write one JSON line: ts, level, event, bound context, then the given fields."""
    record: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "level": level,
        "event": event,
        **_context,
    }
    for key, value in fields.items():
        record[key] = "[redacted]" if key.lower() in _REDACTED_KEYS else value
    sys.stdout.write(json.dumps(record, default=_default, ensure_ascii=True) + "\n")
    sys.stdout.flush()
