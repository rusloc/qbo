"""Runtime configuration for qbo_sync and the etl/ scripts.

Values come from ``etl/.env`` (hand-parsed, no python-dotenv) and are overridden by the process
environment. Error messages and ``repr`` name variables only, never values (CLAUDE.md, spec 9.1).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"  # etl/.env

ENVIRONMENTS = ("sandbox", "prod")

# Settings field -> environment variable name.
ENV_VARS = {
    "db_url": "DB_URL",
    "client_id": "CLIENT_ID",
    "client_secret": "CLIENT_SECRET",
    "realm_id": "REALM_ID",
    "redirect_uri": "REDIRECT_URI",
    "env": "ENV",
}

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_INLINE_COMMENT = re.compile(r"\s+#")


class ConfigError(Exception):
    """Missing or invalid configuration. The message names variables, never values."""


@dataclass(frozen=True, repr=False)
class Settings:
    db_url: str | None
    client_id: str | None
    client_secret: str | None
    realm_id: str | None
    redirect_uri: str | None
    env: str = "sandbox"  # 'sandbox' (default) | 'prod'

    def __post_init__(self) -> None:
        if self.env not in ENVIRONMENTS:
            raise ConfigError("ENV must be 'sandbox' or 'prod'")

    def __repr__(self) -> str:
        # Never show values: realm id, client id, secrets and the DB URL all stay out of logs.
        present = [f.name for f in fields(self) if f.name != "env" and getattr(self, f.name)]
        return f"Settings(env={self.env!r}, set={present})"

    __str__ = __repr__


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a ``KEY=VALUE`` file.

    Supported: blank lines, full-line ``#`` comments, an optional ``export`` prefix, values in
    matching single or double quotes (taken literally), and `` #`` inline comments after an
    unquoted value. A UTF-8 BOM is tolerated.
    """
    values: dict[str, str] = {}
    text = path.read_text(encoding="utf-8-sig")
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not _KEY.fullmatch(key):
            raise ConfigError(f"{path.name} line {lineno}: expected KEY=VALUE")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = _INLINE_COMMENT.split(value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values


def load_settings(*required: str, env_file: Path | None = None) -> Settings:
    """Load settings from ``etl/.env`` (or ``env_file``), overridden by the process environment.

    ``required`` names Settings fields (e.g. ``'db_url'``); a missing or empty one raises
    ``ConfigError("missing: DB_URL, ...")``. ``ENV`` defaults to ``'sandbox'``.
    """
    unknown = [name for name in required if name not in ENV_VARS or name == "env"]
    if unknown:
        raise ValueError(f"unknown settings field(s): {', '.join(unknown)}")

    path = DEFAULT_ENV_FILE if env_file is None else env_file
    file_values = parse_env_file(path) if path.is_file() else {}

    def lookup(var: str) -> str | None:
        value = os.environ.get(var)
        if value is None or not value.strip():
            value = file_values.get(var)
        if value is None or not value.strip():
            return None
        return value.strip()

    values = {name: lookup(var) for name, var in ENV_VARS.items()}
    missing = [ENV_VARS[name] for name in required if values[name] is None]
    if missing:
        raise ConfigError(f"missing: {', '.join(missing)}")

    env = values.pop("env") or "sandbox"
    return Settings(**values, env=env)
