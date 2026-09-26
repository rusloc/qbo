import pytest

import run_dbt
from qbo_sync import config
from qbo_sync.config import ConfigError


@pytest.fixture(autouse=True)
def no_env_file(monkeypatch, tmp_path):
    """Never read a real etl/.env from tests."""
    monkeypatch.setattr(config, "DEFAULT_ENV_FILE", tmp_path / "absent.env")


URL = "postgresql://qbo_etl.abcref:p%40ss%3Aw%2Frd%23x@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"


def test_dbt_env_splits_and_decodes():
    env = run_dbt.dbt_env(URL)
    assert env == {
        "QBO_DB_HOST": "aws-0-eu-central-1.pooler.supabase.com",
        "QBO_DB_PORT": "5432",
        "QBO_DB_NAME": "postgres",
        "QBO_DB_USER": "qbo_etl.abcref",
        "DBT_ENV_SECRET_QBO_DB_PASSWORD": "p@ss:w/rd#x",
    }


def test_dbt_env_defaults_port_and_database():
    env = run_dbt.dbt_env("postgres://u:p@host")
    assert env["QBO_DB_PORT"] == "5432" and env["QBO_DB_NAME"] == "postgres"


@pytest.mark.parametrize(
    "url",
    ["mysql://u:s3cret@h/db", "postgresql://u@h/db", "postgresql://u:s3cret@h:notaport/db", "postgresql://:s3cret@h/db"],
)
def test_dbt_env_errors_name_the_variable_not_the_value(url):
    with pytest.raises(ConfigError) as err:
        run_dbt.dbt_env(url)
    assert "DB_URL" in str(err.value) and "s3cret" not in str(err.value)


def test_main_runs_dbt_in_dbt_dir_with_derived_env(monkeypatch, capsys):
    seen = {}

    class Done:
        returncode = 0

    def fake_run(cmd, cwd, env, check):
        seen.update(cmd=cmd, cwd=cwd, env=env)
        return Done()

    monkeypatch.setenv("DB_URL", URL)
    monkeypatch.setattr(run_dbt.subprocess, "run", fake_run)
    assert run_dbt.main(["build", "--vars", "{full_reload: true}"]) == 0
    assert seen["cmd"][1:] == ["build", "--vars", "{full_reload: true}"]
    assert seen["cwd"] == run_dbt.DBT_DIR
    assert seen["env"]["DBT_PROFILES_DIR"] == str(run_dbt.DBT_DIR)
    assert seen["env"]["DBT_ENV_SECRET_QBO_DB_PASSWORD"] == "p@ss:w/rd#x"
    assert "DB_URL" not in seen["env"]
    out = capsys.readouterr()
    assert "p@ss" not in out.out + out.err


def test_main_without_args_prints_usage(capsys):
    assert run_dbt.main([]) == 2
    assert "Usage" in capsys.readouterr().out
