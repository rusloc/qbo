"""qbo_sync.__main__: CLI parsing, required settings per command, clean config failure, dispatch."""

from __future__ import annotations

import pytest

from qbo_sync import __main__ as cli
from qbo_sync import backfill, cdc, config, db
from qbo_sync.entities import ALL_ENTITIES, CDC_ENTITIES


class Settings:
    db_url = "postgresql://example.invalid/db"
    client_id = "cid"
    client_secret = "secret"
    realm_id = "123"
    redirect_uri = "http://localhost:8765/callback"
    env = "sandbox"


class FakeConn:
    closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def no_env_file(monkeypatch, tmp_path):
    """Real config.load_settings with an empty environment and no .env file."""
    for var in config.ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    calls: list[tuple[str, ...]] = []
    real = config.load_settings

    def load_settings(*required: str, env_file=None):
        calls.append(required)
        return real(*required, env_file=tmp_path / "absent.env")

    monkeypatch.setattr(config, "load_settings", load_settings)
    return calls


def test_status_without_env_fails_cleanly_naming_db_url(no_env_file, capsys) -> None:
    assert cli.main(["status"]) == 2
    assert no_env_file == [("db_url",)]
    output = capsys.readouterr()
    assert "DB_URL" in output.err and "Traceback" not in output.err
    assert '"event": "config_error"' in output.out


@pytest.mark.parametrize(
    ("argv", "missing"),
    [
        (["auth"], "CLIENT_ID, CLIENT_SECRET, REALM_ID, REDIRECT_URI, DB_URL"),
        (["backfill"], "CLIENT_ID, CLIENT_SECRET, REALM_ID, DB_URL"),
        (["cdc"], "CLIENT_ID, CLIENT_SECRET, REALM_ID, DB_URL"),
    ],
)
def test_each_command_names_exactly_its_missing_vars(no_env_file, capsys, argv, missing) -> None:
    assert cli.main(argv) == 2
    assert f"missing: {missing}" in capsys.readouterr().err


def test_help_lists_the_four_commands(capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["--help"])
    assert caught.value.code == 0
    out = capsys.readouterr().out
    assert all(command in out for command in ("auth", "backfill", "cdc", "status"))


def test_unknown_entity_is_a_usage_error_before_config_is_read(no_env_file, capsys) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["backfill", "Invoices"])
    assert caught.value.code == 2
    assert no_env_file == []
    assert "valid entities" in capsys.readouterr().err


def test_backfill_dispatch_canonicalises_entities_and_lands_through_db(monkeypatch) -> None:
    conn = FakeConn()
    seen: dict = {}
    monkeypatch.setattr(config, "load_settings", lambda *required, env_file=None: Settings())
    monkeypatch.setattr(db, "connect", lambda settings: conn)

    def fake_run(conn_, client, entities, *, land):
        seen.update(conn=conn_, entities=entities, land=land)
        return 1

    monkeypatch.setattr(backfill, "run", fake_run)
    assert cli.main(["backfill", "invoice", "BILL", "Invoice"]) == 1
    assert seen["entities"] == ("Invoice", "Bill")
    assert seen["conn"] is conn and seen["land"] is db.land_raw
    assert conn.closed


def test_cdc_dispatch_runs_all_cdc_entities(monkeypatch) -> None:
    seen: dict = {}
    monkeypatch.setattr(config, "load_settings", lambda *required, env_file=None: Settings())
    monkeypatch.setattr(db, "connect", lambda settings: FakeConn())
    monkeypatch.setattr(
        cdc, "run", lambda conn, client, entities, *, land: seen.update(entities=entities) or 0
    )
    assert cli.main(["cdc"]) == 0
    assert seen["entities"] == CDC_ENTITIES == ALL_ENTITIES
    assert "Budget" in CDC_ENTITIES


def test_unparseable_db_url_is_a_config_error_not_a_crash(monkeypatch, capsys) -> None:
    monkeypatch.setattr(config, "load_settings", lambda *required, env_file=None: Settings())

    def bad_connect(settings):
        raise config.ConfigError("DB_URL cannot be parsed")

    monkeypatch.setattr(db, "connect", bad_connect)
    assert cli.main(["status"]) == 2
    assert "DB_URL cannot be parsed" in capsys.readouterr().err


def test_unexpected_error_exits_1_with_a_log_line(monkeypatch, capsys) -> None:
    monkeypatch.setattr(config, "load_settings", lambda *required, env_file=None: Settings())

    def broken_connect(settings):
        raise OSError("connection refused")

    monkeypatch.setattr(db, "connect", broken_connect)
    assert cli.main(["status"]) == 1
    out = capsys.readouterr().out
    assert '"event": "run_failed"' in out and '"exit_code": 1' in out
