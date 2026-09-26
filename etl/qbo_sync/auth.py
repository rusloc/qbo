"""Intuit OAuth 2.0 for qbo_sync (spec §1, ADR-0007).

- `run_auth`: authorization-code flow. A local callback server listens on REDIRECT_URI, the
  browser opens the Intuit consent page, the callback's `state` (CSRF) and `realmId` are checked,
  the code is exchanged, and the refresh token is stored in Vault via qbo.refresh_token_store().
- `refresh`: ONE transaction: qbo.refresh_token_lock() (advisory lock + current token) -> POST to
  Intuit -> qbo.refresh_token_store(new) -> COMMIT, and only then is the access token handed out.
  The advisory lock makes refreshes single-flight across processes.
- The access token lives in memory only (`AccessTokens`). No token, secret, auth code, state or
  realmId value ever reaches a log line or an exception message.
- The token POST is never retried: after a timeout Intuit may already have rotated the token.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Self

from qbo_sync.client import utcnow
from qbo_sync.jsonlog import log
from qbo_sync.state import rollback_quietly

AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
SCOPE = "com.intuit.quickbooks.accounting"
REFRESH_MARGIN = timedelta(minutes=10)
CALLBACK_TIMEOUT_S = 300
TOKEN_TIMEOUT_S = 30

LOCK_SQL = """
select
     qbo.refresh_token_lock()      _refresh_token
"""

STORE_SQL = """
select
     qbo.refresh_token_store(%s)   _stored
"""

TokenPost = Callable[[Mapping[str, str]], dict[str, Any]]


class AuthError(Exception):
    """OAuth / token failure. Messages never carry token, code, state or realmId values."""


def _oauth_error_word(err: urllib.error.HTTPError) -> str:
    """The OAuth `error` field (e.g. invalid_grant) if it is a plain word, else ''."""
    try:
        value = json.loads(err.read().decode("utf-8", errors="replace")).get("error", "")
    except (ValueError, OSError, AttributeError):
        return ""
    return value if isinstance(value, str) and re.fullmatch(r"[a-z_]{1,40}", value) else ""


def token_endpoint(
    client_id: str,
    client_secret: str,
    *,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> TokenPost:
    """Return a function that POSTs a form to Intuit's token endpoint (HTTP Basic client auth)."""
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")

    def post(form: Mapping[str, str]) -> dict[str, Any]:
        request = urllib.request.Request(
            TOKEN_URL,
            data=urllib.parse.urlencode(form).encode("ascii"),
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {basic}",
            },
        )
        try:
            with urlopen(request, timeout=TOKEN_TIMEOUT_S) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            word = _oauth_error_word(err)
            hint = (
                "; the stored refresh token is expired or revoked: run `python -m qbo_sync auth`"
                if word == "invalid_grant"
                else ""
            )
            raise AuthError(
                f"Intuit token endpoint refused the request: HTTP {err.code} {word}{hint}".strip()
            ) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            raise AuthError(f"Intuit token endpoint unreachable ({type(err).__name__})") from None

    return post


def _ttl_days(body: Mapping[str, Any]) -> float | None:
    seconds = body.get("x_refresh_token_expires_in")
    return round(int(seconds) / 86400, 1) if isinstance(seconds, int) else None


def refresh(
    conn: Any, post: TokenPost, *, now: Callable[[], datetime] = utcnow
) -> tuple[str, datetime]:
    """Rotate the refresh token single-flight and return (access_token, expires_at).

    lock -> Intuit POST -> store -> COMMIT happen in this order inside one transaction; the
    access token is returned only after the commit (spec §1: persist before use).
    """
    row = conn.execute(LOCK_SQL).fetchone()
    current = row[0] if row else None
    if not current:
        rollback_quietly(conn)
        raise AuthError("No QBO refresh token in Vault yet: run `python -m qbo_sync auth` first.")
    try:
        body = post({"grant_type": "refresh_token", "refresh_token": current})
    except BaseException:
        rollback_quietly(conn)
        raise
    access = body.get("access_token")
    rotated = body.get("refresh_token")
    if not access or not rotated:
        rollback_quietly(conn)
        raise AuthError("Intuit token response lacks access_token or refresh_token; nothing stored.")
    try:
        conn.execute(STORE_SQL, (rotated,))
        conn.commit()
    except Exception as err:  # noqa: BLE001  # any failure needs rollback + hint
        rollback_quietly(conn)
        sqlstate = getattr(err, "sqlstate", None)
        detail = type(err).__name__ + (f" {sqlstate}" if sqlstate else "")
        raise AuthError(
            f"Intuit rotated the refresh token but storing it in Vault failed ({detail}); "
            "if the next run fails with invalid_grant, run `python -m qbo_sync auth`."
        ) from None
    expires_in = int(body.get("expires_in", 3600))
    log(
        "token_refreshed",
        access_token_ttl_s=expires_in,
        refresh_token_ttl_days=_ttl_days(body),
    )
    return access, now() + timedelta(seconds=expires_in)


class AccessTokens:
    """In-memory access token. Refreshes before first use and when < 10 min of life remain."""

    def __init__(
        self, conn: Any, post: TokenPost, *, now: Callable[[], datetime] = utcnow
    ) -> None:
        self._conn = conn
        self._post = post
        self._now = now
        self._access: str | None = None
        self._expires_at: datetime | None = None

    def token(self) -> str:
        if (
            self._access is None
            or self._expires_at is None
            or self._expires_at - self._now() < REFRESH_MARGIN
        ):
            self._access, self._expires_at = refresh(self._conn, self._post, now=self._now)
        return self._access

    def invalidate(self) -> None:
        self._access = None


# --- authorization-code flow -------------------------------------------------------------


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "scope": SCOPE,
            "redirect_uri": redirect_uri,
            "state": state,
        },
        quote_via=urllib.parse.quote,
    )
    return f"{AUTHORIZE_URL}?{query}"


def parse_redirect_uri(uri: str | None) -> tuple[str, int, str]:
    """(host, port, path) of a local http REDIRECT_URI such as http://localhost:8765/callback."""
    split = urllib.parse.urlsplit(uri or "")
    if split.scheme != "http" or split.hostname not in {"localhost", "127.0.0.1"} or not split.port:
        raise AuthError(
            "REDIRECT_URI must be a local http address with a port, e.g. "
            "http://localhost:8765/callback, registered in the Intuit app's redirect URIs."
        )
    return split.hostname, split.port, split.path or "/"


def _one(params: Mapping[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    return values[0] if values else None


def _same(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def validate_callback(
    params: Mapping[str, list[str]], *, expected_state: str, expected_realm: str
) -> str:
    """Return the authorization code, or raise AuthError. Checks run before any token exchange."""
    error = _one(params, "error")
    if error:
        word = error if re.fullmatch(r"[a-z_]{1,40}", error) else "unrecognised"
        raise AuthError(f"Intuit returned an authorization error ({word}); nothing stored.")
    state = _one(params, "state")
    if state is None or not _same(state, expected_state):
        raise AuthError("Callback state does not match this run (possible CSRF); nothing stored.")
    realm = _one(params, "realmId")
    if realm is None or not _same(realm, expected_realm):
        raise AuthError(
            "The company chosen on the consent page is not the one in REALM_ID; nothing stored. "
            "Run auth again and pick the sandbox company whose Company ID is in REALM_ID."
        )
    code = _one(params, "code")
    if not code:
        raise AuthError("Callback carries no authorization code; nothing stored.")
    return code


class _CallbackHandler(BaseHTTPRequestHandler):
    server: _CallbackHTTPServer

    def do_GET(self) -> None:
        split = urllib.parse.urlsplit(self.path)
        if split.path != self.server.expected_path:
            self.send_error(404)
            return
        self.server.params = urllib.parse.parse_qs(split.query)
        body = (
            b"<!doctype html><html><body style='font-family:Segoe UI,sans-serif'>"
            b"<p>QBO P&amp;L: authorization received. You can close this tab and return to "
            b"the terminal.</p></body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        # Silenced on purpose: the default writes the request line - code, state and realmId -
        # to stderr.
        return


class _CallbackHTTPServer(HTTPServer):
    def __init__(self, host: str, port: int, expected_path: str) -> None:
        super().__init__((host, port), _CallbackHandler)
        self.expected_path = expected_path
        self.params: dict[str, list[str]] | None = None


class CallbackServer:
    """Local one-shot HTTP listener for the OAuth redirect. Bind before opening the browser."""

    def __init__(self, host: str, port: int, path: str) -> None:
        self._server = _CallbackHTTPServer(host, port, path)
        self._server.timeout = 1

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def wait(
        self, timeout_s: float, *, monotonic: Callable[[], float] = time.monotonic
    ) -> dict[str, list[str]]:
        deadline = monotonic() + timeout_s
        while self._server.params is None:
            if monotonic() > deadline:
                raise AuthError(
                    f"No callback from Intuit within {int(timeout_s)} s; run auth again."
                )
            self._server.handle_request()
        return self._server.params

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.server_close()


def run_auth(
    conn: Any,
    settings: Any,
    post: TokenPost,
    *,
    open_browser: Callable[[str], bool] = webbrowser.open,
    timeout_s: float = CALLBACK_TIMEOUT_S,
) -> None:
    """Authorization-code flow; stores the first refresh token in Vault and commits."""
    host, port, path = parse_redirect_uri(settings.redirect_uri)
    state = secrets.token_urlsafe(32)
    url = authorize_url(settings.client_id, settings.redirect_uri, state)
    with CallbackServer(host, port, path) as server:
        log("auth_waiting_for_consent", callback_port=server.port, timeout_s=timeout_s)
        if not open_browser(url):
            # Terminal fallback only; the URL carries the public client id and a one-time state.
            print(f"Open this URL in a browser to authorize QBO access:\n{url}", file=sys.stderr)
        params = server.wait(timeout_s)
    code = validate_callback(params, expected_state=state, expected_realm=settings.realm_id)
    log("auth_callback_accepted")
    body = post(
        {"grant_type": "authorization_code", "code": code, "redirect_uri": settings.redirect_uri}
    )
    rotated = body.get("refresh_token")
    if not rotated:
        raise AuthError("Intuit token response lacks refresh_token; nothing stored.")
    try:
        conn.execute(STORE_SQL, (rotated,))
        conn.commit()
    except Exception as err:  # noqa: BLE001  # any failure needs rollback + hint
        rollback_quietly(conn)
        raise AuthError(
            f"Storing the refresh token in Vault failed ({type(err).__name__}); run auth again."
        ) from None
    log("auth_refresh_token_stored", refresh_token_ttl_days=_ttl_days(body))
