from datetime import UTC

import pytest

import load_demo
from qbo_sync import config


class FakeConn:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def no_env_file(monkeypatch, tmp_path):
    """Never read a real etl/.env from tests."""
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", tmp_path / "absent.env")


@pytest.fixture
def demo_dir(tmp_path):
    (tmp_path / "Account.json").write_text('[\n{"Id":"1","CurrentBalance":0.10},\n{"Id":"2"}\n]\n', encoding="utf-8")
    (tmp_path / "Invoice.json").write_text('[\n{"Id":"101","TotalAmt":12.30}\n]\n', encoding="utf-8")
    return tmp_path


def test_dry_run_counts_without_database(demo_dir, capsys, monkeypatch):
    monkeypatch.setattr(load_demo, "connect", lambda s: pytest.fail("dry run must not connect"))
    assert load_demo.main(["--dir", str(demo_dir), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Account" in out and "Invoice" in out and "3 objects" in out


def test_load_lands_every_file_with_fixed_synced_at(demo_dir, monkeypatch, capsys):
    calls = []

    def fake_land(conn, entity, doc, path, synced_at):
        calls.append((entity, doc, path, synced_at))
        return doc.count('"Id"')

    conn = FakeConn()
    monkeypatch.setenv("DB_URL", "postgresql://u:secret@h/db")
    monkeypatch.setattr(load_demo, "connect", lambda settings: conn)
    monkeypatch.setattr(load_demo, "land_raw", fake_land)
    assert load_demo.main(["--dir", str(demo_dir)]) == 0

    assert [c[0] for c in calls] == ["Account", "Invoice"]
    assert all(c[2] == () for c in calls)  # each file is the array itself
    assert all(c[3] == load_demo.DEMO_SYNCED_AT for c in calls)
    assert calls[1][1] == (demo_dir / "Invoice.json").read_text(encoding="utf-8")  # text passed unparsed
    assert conn.commits == 1
    out = capsys.readouterr().out
    assert "3 rows inserted" in out and "secret" not in out


def test_fixed_synced_at_is_after_the_data_window():
    assert load_demo.DEMO_SYNCED_AT.tzinfo is UTC
    assert load_demo.DEMO_SYNCED_AT.date().isoformat() == "2026-09-01"


def test_missing_db_url_is_reported_by_name(demo_dir, monkeypatch, capsys):
    monkeypatch.delenv("DB_URL", raising=False)
    assert load_demo.main(["--dir", str(demo_dir)]) == 2
    assert "missing: DB_URL" in capsys.readouterr().err


def test_empty_folder_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_demo.demo_files(tmp_path)
