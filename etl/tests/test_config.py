from pathlib import Path

import pytest

from qbo_sync.config import ConfigError, Settings, load_settings, parse_env_file

ALL_VARS = ("DB_URL", "CLIENT_ID", "CLIENT_SECRET", "REALM_ID", "REDIRECT_URI", "ENV")
SECRET = "s3cr3t-Value"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ALL_VARS:
        monkeypatch.delenv(var, raising=False)


def write_env(tmp_path: Path, text: str, encoding: str = "utf-8") -> Path:
    path = tmp_path / ".env"
    path.write_text(text, encoding=encoding)
    return path


def test_parse_env_file_syntax(tmp_path):
    path = write_env(
        tmp_path,
        "# comment\n"
        "\n"
        "DB_URL=postgresql://u:p%40w@h:5432/postgres\n"
        "export CLIENT_ID = abc  \n"
        "CLIENT_SECRET=\"quoted # not a comment\"\n"
        "REALM_ID='123'\n"
        "ENV=sandbox   # inline comment\n"
        "REDIRECT_URI=http://localhost:8765/callback#frag\n",
    )
    values = parse_env_file(path)
    assert values == {
        "DB_URL": "postgresql://u:p%40w@h:5432/postgres",
        "CLIENT_ID": "abc",
        "CLIENT_SECRET": "quoted # not a comment",
        "REALM_ID": "123",
        "ENV": "sandbox",
        "REDIRECT_URI": "http://localhost:8765/callback#frag",
    }


def test_parse_env_file_tolerates_bom(tmp_path):
    path = write_env(tmp_path, "DB_URL=x\n", encoding="utf-8-sig")
    assert parse_env_file(path) == {"DB_URL": "x"}


def test_parse_env_file_bad_line_names_line_not_value(tmp_path):
    path = write_env(tmp_path, f"DB_URL=ok\nthis line has {SECRET}\n")
    with pytest.raises(ConfigError) as err:
        parse_env_file(path)
    assert "line 2" in str(err.value)
    assert SECRET not in str(err.value)


def test_load_settings_reads_file_and_defaults_env(tmp_path):
    path = write_env(tmp_path, "DB_URL=postgresql://file\nREALM_ID=42\n")
    s = load_settings("db_url", env_file=path)
    assert s.db_url == "postgresql://file"
    assert s.realm_id == "42"
    assert s.client_id is None
    assert s.env == "sandbox"


def test_process_env_overrides_file(tmp_path, monkeypatch):
    path = write_env(tmp_path, "DB_URL=postgresql://file\nENV=sandbox\n")
    monkeypatch.setenv("DB_URL", "postgresql://process")
    monkeypatch.setenv("ENV", "prod")
    s = load_settings(env_file=path)
    assert s.db_url == "postgresql://process"
    assert s.env == "prod"


def test_empty_process_value_falls_back_to_file(tmp_path, monkeypatch):
    path = write_env(tmp_path, "DB_URL=postgresql://file\n")
    monkeypatch.setenv("DB_URL", "  ")
    assert load_settings("db_url", env_file=path).db_url == "postgresql://file"


def test_missing_required_names_env_vars_only(tmp_path):
    path = write_env(tmp_path, f"CLIENT_SECRET={SECRET}\nCLIENT_ID=\n")
    with pytest.raises(ConfigError) as err:
        load_settings("db_url", "client_id", "client_secret", env_file=path)
    assert str(err.value) == "missing: DB_URL, CLIENT_ID"
    assert SECRET not in str(err.value)


def test_no_env_file_is_fine(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_URL", "postgresql://process")
    s = load_settings("db_url", env_file=tmp_path / "absent.env")
    assert s.db_url == "postgresql://process"


def test_invalid_env_rejected_without_echo(tmp_path):
    path = write_env(tmp_path, "ENV=production\n")
    with pytest.raises(ConfigError) as err:
        load_settings(env_file=path)
    assert "production" not in str(err.value)


def test_unknown_required_field_is_a_programming_error(tmp_path):
    with pytest.raises(ValueError):
        load_settings("dburl", env_file=tmp_path / "absent.env")


def test_repr_hides_values():
    s = Settings(
        db_url=f"postgresql://u:{SECRET}@h/db",
        client_id="cid",
        client_secret=SECRET,
        realm_id="9130",
        redirect_uri=None,
    )
    text = repr(s) + str(s)
    for value in (SECRET, "cid", "9130", "postgresql"):
        assert value not in text
    assert "db_url" in text
    assert s.env == "sandbox"


def test_settings_is_frozen():
    s = Settings(None, None, None, None, None, "prod")
    with pytest.raises(AttributeError):
        s.env = "sandbox"  # type: ignore[misc]
