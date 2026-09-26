"""Run dbt for the qbo_pnl project with connection settings derived from DB_URL.

DB_URL (etl/.env or the environment) is the single database secret. This wrapper splits it into
the variables dbt/profiles.yml reads (QBO_DB_HOST, QBO_DB_PORT, QBO_DB_NAME, QBO_DB_USER,
DBT_ENV_SECRET_QBO_DB_PASSWORD; URL-decoded), sets them only in the dbt subprocess environment,
and runs dbt from dbt/ with dbt/ as the profiles dir. All arguments are passed through.

Usage (from the repo root):
    etl/.venv/Scripts/python etl/run_dbt.py parse
    etl/.venv/Scripts/python etl/run_dbt.py build
    etl/.venv/Scripts/python etl/run_dbt.py build --vars "{full_reload: true}"
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from qbo_sync.config import ConfigError, load_settings

DBT_DIR = Path(__file__).resolve().parent.parent / "dbt"


def dbt_env(db_url: str) -> dict[str, str]:
    """Split a postgresql:// URL into the dbt profile variables. Errors never echo the URL."""
    parts = urlsplit(db_url)
    if parts.scheme not in ("postgresql", "postgres"):
        raise ConfigError("DB_URL must start with postgresql://")
    try:
        port = parts.port or 5432
    except ValueError:
        raise ConfigError("DB_URL has an invalid port") from None
    host, user, password = parts.hostname, parts.username, parts.password
    missing = [name for name, value in (("host", host), ("user", user), ("password", password)) if not value]
    if missing:
        raise ConfigError(f"DB_URL is missing: {', '.join(missing)}")
    return {
        "QBO_DB_HOST": host,
        "QBO_DB_PORT": str(port),
        "QBO_DB_NAME": unquote(parts.path.lstrip("/")) or "postgres",
        "QBO_DB_USER": unquote(user),
        "DBT_ENV_SECRET_QBO_DB_PASSWORD": unquote(password),
    }


def dbt_executable() -> str:
    """The dbt next to this interpreter (etl/.venv), else the one on PATH."""
    scripts = Path(sys.executable).parent
    for name in ("dbt.exe", "dbt"):
        candidate = scripts / name
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("dbt")
    if not found:
        raise FileNotFoundError("dbt not found; install etl/requirements.txt into etl/.venv")
    return found


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(__doc__)
        return 2
    try:
        settings = load_settings("db_url")
        env = {**os.environ, **dbt_env(settings.db_url), "DBT_PROFILES_DIR": str(DBT_DIR)}
    except ConfigError as err:
        print(f"config error: {err}", file=sys.stderr)
        return 2
    env.pop("DB_URL", None)  # dbt needs only the split variables
    completed = subprocess.run([dbt_executable(), *args], cwd=DBT_DIR, env=env, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
