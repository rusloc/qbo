"""qbo_sync: QBO Accounting API -> qbo.raw_entity landing CLI (spec §4 Phase 1).

Run from etl/ with the project venv:

    .venv/Scripts/python -m qbo_sync auth                 one-time browser consent -> Vault
    .venv/Scripts/python -m qbo_sync backfill [entity...]  full re-read (default: all entities)
    .venv/Scripts/python -m qbo_sync cdc                  daily incremental (Task Scheduler)
    .venv/Scripts/python -m qbo_sync status               watermarks, CDC window, token present

Exit codes: 0 ok; 1 run failed or refused (details in the JSON lines on stdout);
2 usage error or missing configuration.
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
import uuid
from collections.abc import Sequence
from contextlib import closing
from typing import Any

from qbo_sync import auth, backfill, cdc, config, db, status
from qbo_sync.client import QboClient
from qbo_sync.entities import ALL_ENTITIES, CDC_ENTITIES, LANDED_ONLY, canonical
from qbo_sync.jsonlog import bind, log

# Settings field names per command; config.load_settings reports them as env var names.
REQUIRED_SETTINGS: dict[str, tuple[str, ...]] = {
    "auth": ("client_id", "client_secret", "realm_id", "redirect_uri", "db_url"),
    "backfill": ("client_id", "client_secret", "realm_id", "db_url"),
    "cdc": ("client_id", "client_secret", "realm_id", "db_url"),
    "status": ("db_url",),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qbo_sync",
        description="Land QuickBooks Online data in Supabase schema qbo (raw_entity, sync_state).",
        epilog=(
            "Configuration: environment variables or etl/.env - CLIENT_ID, CLIENT_SECRET, "
            "REALM_ID, REDIRECT_URI (auth only, e.g. http://localhost:8765/callback), DB_URL, "
            "ENV=sandbox|prod (default sandbox). The refresh token lives in Supabase Vault "
            "(ADR-0007), never in env. Exit codes: 0 ok, 1 failed/refused, 2 usage/config."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    commands.add_parser(
        "auth", help="one-time OAuth consent in the browser; stores the refresh token in Vault"
    )
    backfill_parser = commands.add_parser(
        "backfill", help="full re-read of all or the named entities (ORDERBY Id, 1000 per page)"
    )
    backfill_parser.add_argument(
        "entities",
        nargs="*",
        metavar="entity",
        help=(
            f"default: all - {', '.join(ALL_ENTITIES)} "
            f"({', '.join(LANDED_ONLY)}: landed raw only, no transform yet)"
        ),
    )
    commands.add_parser(
        "cdc", help="incremental: changes and deletes since each entity's watermark (max 30 days)"
    )
    commands.add_parser(
        "status", help="watermarks, last status, days left in the CDC window, token stored"
    )
    return parser


def _dispatch(command: str, conn: Any, settings: Any, entities: Sequence[str]) -> int:
    if command == "status":
        return status.run(conn, ALL_ENTITIES)
    post = auth.token_endpoint(settings.client_id, settings.client_secret)
    if command == "auth":
        auth.run_auth(conn, settings, post)
        return 0
    client = QboClient(settings.env, settings.realm_id, auth.AccessTokens(conn, post))
    if command == "backfill":
        return backfill.run(conn, client, entities, land=db.land_raw)
    return cdc.run(conn, client, CDC_ENTITIES, land=db.land_raw)


def _config_failure(command: str, err: Exception) -> int:
    log("config_error", "error", message=str(err))
    print(f"qbo_sync {command}: configuration error - {err}", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    entities: tuple[str, ...] = ALL_ENTITIES
    if args.command == "backfill" and args.entities:
        try:
            entities = tuple(dict.fromkeys(canonical(name) for name in args.entities))
        except ValueError as err:
            parser.error(str(err))
    bind(run_id=uuid.uuid4().hex[:12], command=args.command)
    try:
        settings = config.load_settings(*REQUIRED_SETTINGS[args.command])
    except config.ConfigError as err:
        return _config_failure(args.command, err)
    started = time.monotonic()
    log(
        "run_started",
        env=settings.env,
        entities=list(entities) if args.command == "backfill" else None,
    )
    try:
        with closing(db.connect(settings)) as conn:
            code = _dispatch(args.command, conn, settings, entities)
    except config.ConfigError as err:
        return _config_failure(args.command, err)
    except auth.AuthError as err:
        log("run_failed", "error", error_type="AuthError", message=str(err))
        code = 1
    except Exception as err:  # noqa: BLE001  # last-resort handler of the CLI
        first_line = (str(err).splitlines() or [""])[0]
        log("run_failed", "error", error_type=type(err).__name__, message=first_line)
        traceback.print_exc(file=sys.stderr)
        code = 1
    log(
        "run_finished",
        "info" if code == 0 else "error",
        exit_code=code,
        duration_s=round(time.monotonic() - started, 1),
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
