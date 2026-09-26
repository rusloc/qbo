"""qbo_sync.auth: persist-before-use refresh, callback CSRF / realm checks, no secret in any output."""

from __future__ import annotations

import base64
import io
import json
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from email.message import Message
from types import SimpleNamespace

import pytest

from qbo_sync import auth
from qbo_sync.client import QboApiError, QboClient
from qbo_sync.jsonlog import log

CLIENT_ID = "CID-SENTINEL-7781"
CLIENT_SECRET = "CSECRET-SENTINEL-5512"
REALM = "REALM-SENTINEL-4620"
OLD_RT = "RT-OLD-SENTINEL-1111"
NEW_RT = "RT-NEW-SENTINEL-2222"
NEW_AT = "AT-NEW-SENTINEL-3333"
CODE = "CODE-SENTINEL-4444"
SENTINELS = (CLIENT_ID, CLIENT_SECRET, REALM, OLD_RT, NEW_RT, NEW_AT, CODE)
T0 = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


class FakeCursor:
    def __init__(self, row: tuple | None) -> None:
        self.row = row

    def fetchone(self) -> tuple | None:
        return self.row


class FakeConn:
    """Records lock / store / commit / rollback in `events`; `store_fails` simulates a DB error."""

    def __init__(self, events: list[str], stored_token: str | None = OLD_RT, store_fails=False) -> None:
        self.events = events
        self.stored_token = stored_token
        self.store_fails = store_fails
        self.stored: list[str] = []

    def execute(self, sql: str, params: tuple = ()) -> FakeCursor:
        if "refresh_token_lock" in sql:
            self.events.append("lock")
            return FakeCursor((self.stored_token,))
        if "refresh_token_store" in sql:
            self.events.append("store")
            if self.store_fails:
                raise RuntimeError("permission denied")
            self.stored.append(params[0])
            return FakeCursor((None,))
        raise AssertionError(f"unexpected SQL: {sql}")

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")


def token_post(events: list[str], body: dict | None = None, forms: list | None = None):
    def post(form):
        events.append("post")
        if forms is not None:
            forms.append(dict(form))
        return body or {
            "token_type": "bearer",
            "access_token": NEW_AT,
            "expires_in": 3600,
            "refresh_token": NEW_RT,
            "x_refresh_token_expires_in": 8726400,
        }

    return post


# --- refresh: persist before use ------------------------------------------------------------


def test_refresh_persists_the_rotated_token_before_the_access_token_is_used() -> None:
    events: list[str] = []
    conn = FakeConn(events)
    forms: list[dict] = []
    tokens = auth.AccessTokens(conn, token_post(events, forms=forms), now=lambda: T0)
    seen: list[str] = []

    def urlopen(request, timeout):
        events.append("api")
        seen.append(request.get_header("Authorization"))
        return io.BytesIO(b"{}")

    client = QboClient("sandbox", REALM, tokens, urlopen=urlopen, sleep=lambda s: None)
    client.query("select * from Invoice")
    assert events == ["lock", "post", "store", "commit", "api"]
    assert forms == [{"grant_type": "refresh_token", "refresh_token": OLD_RT}]
    assert conn.stored == [NEW_RT]
    assert seen == [f"Bearer {NEW_AT}"]


def test_no_stored_token_stops_before_calling_intuit() -> None:
    events: list[str] = []
    with pytest.raises(auth.AuthError, match="qbo_sync auth"):
        auth.refresh(FakeConn(events, stored_token=None), token_post(events))
    assert events == ["lock", "rollback"]


def test_intuit_refusal_rolls_back_and_stores_nothing() -> None:
    events: list[str] = []

    def post(form):
        events.append("post")
        raise auth.AuthError("Intuit token endpoint refused the request: HTTP 400 invalid_grant")

    conn = FakeConn(events)
    with pytest.raises(auth.AuthError, match="invalid_grant"):
        auth.refresh(conn, post)
    assert events == ["lock", "post", "rollback"]
    assert conn.stored == []


def test_store_failure_is_reported_without_handing_out_the_access_token() -> None:
    events: list[str] = []
    with pytest.raises(auth.AuthError, match="storing it in Vault failed") as caught:
        auth.refresh(FakeConn(events, store_fails=True), token_post(events))
    assert events == ["lock", "post", "store", "rollback"]
    assert all(s not in str(caught.value) for s in SENTINELS)


def test_access_token_is_reused_until_ten_minutes_before_expiry() -> None:
    events: list[str] = []
    clock = [T0]
    tokens = auth.AccessTokens(FakeConn(events), token_post(events), now=lambda: clock[0])
    tokens.token()
    clock[0] = T0 + timedelta(minutes=49)
    tokens.token()
    assert events.count("post") == 1
    clock[0] = T0 + timedelta(minutes=51)
    tokens.token()
    assert events.count("post") == 2
    tokens.invalidate()
    tokens.token()
    assert events.count("post") == 3


# --- token endpoint -----------------------------------------------------------------------


def test_token_endpoint_posts_form_with_basic_client_auth() -> None:
    captured: list[urllib.request.Request] = []

    def urlopen(request, timeout):
        captured.append(request)
        return io.BytesIO(json.dumps({"access_token": "a", "refresh_token": "r"}).encode())

    post = auth.token_endpoint(CLIENT_ID, CLIENT_SECRET, urlopen=urlopen)
    post({"grant_type": "refresh_token", "refresh_token": OLD_RT})
    request = captured[0]
    assert request.full_url == auth.TOKEN_URL and request.get_method() == "POST"
    expected = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    assert request.get_header("Authorization") == f"Basic {expected}"
    assert urllib.parse.parse_qs(request.data.decode())["grant_type"] == ["refresh_token"]


def test_token_endpoint_error_names_invalid_grant_but_no_secret() -> None:
    def urlopen(request, timeout):
        body = io.BytesIO(json.dumps({"error": "invalid_grant", "detail": OLD_RT}).encode())
        raise urllib.error.HTTPError(request.full_url, 400, "Bad Request", Message(), body)

    post = auth.token_endpoint(CLIENT_ID, CLIENT_SECRET, urlopen=urlopen)
    with pytest.raises(auth.AuthError) as caught:
        post({"grant_type": "refresh_token", "refresh_token": OLD_RT})
    message = str(caught.value)
    assert "invalid_grant" in message and "qbo_sync auth" in message
    assert all(s not in message for s in SENTINELS)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


# --- callback validation --------------------------------------------------------------------


def params(**values: str) -> dict[str, list[str]]:
    return {k: [v] for k, v in values.items()}


def test_callback_with_matching_state_and_realm_returns_the_code() -> None:
    got = auth.validate_callback(
        params(code=CODE, state="s-1", realmId=REALM), expected_state="s-1", expected_realm=REALM
    )
    assert got == CODE


@pytest.mark.parametrize(
    ("values", "match"),
    [
        ({"code": CODE, "state": "forged", "realmId": REALM}, "state does not match"),
        ({"code": CODE, "realmId": REALM}, "state does not match"),
        ({"code": CODE, "state": "s-1", "realmId": "9999999999"}, "not the one in REALM_ID"),
        ({"code": CODE, "state": "s-1"}, "not the one in REALM_ID"),
        ({"state": "s-1", "realmId": REALM}, "no authorization code"),
        ({"error": "access_denied", "state": "s-1"}, "access_denied"),
    ],
)
def test_callback_is_rejected(values: dict[str, str], match: str) -> None:
    with pytest.raises(auth.AuthError, match=match) as caught:
        auth.validate_callback(params(**values), expected_state="s-1", expected_realm=REALM)
    assert all(s not in str(caught.value) for s in SENTINELS)


def test_authorize_url_requests_the_accounting_scope_only() -> None:
    url = auth.authorize_url(CLIENT_ID, "http://localhost:8765/callback", "s-1")
    split = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(split.query)
    assert f"{split.scheme}://{split.netloc}{split.path}" == auth.AUTHORIZE_URL
    assert query["scope"] == ["com.intuit.quickbooks.accounting"]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == ["http://localhost:8765/callback"]
    assert query["state"] == ["s-1"]


@pytest.mark.parametrize(
    "uri",
    [None, "https://localhost:8765/callback", "http://example.com:8765/callback", "http://localhost/cb"],
)
def test_redirect_uri_must_be_local_http_with_port(uri: str | None) -> None:
    with pytest.raises(auth.AuthError, match="REDIRECT_URI"):
        auth.parse_redirect_uri(uri)


# --- end-to-end auth over a real loopback callback -------------------------------------------


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def browser_that_consents(realm: str, state_override: str | None = None):
    """Stands in for the browser + Intuit: hits the local callback with code/state/realmId."""

    def open_browser(url: str) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        redirect = query["redirect_uri"][0]
        state = state_override or query["state"][0]

        def visit() -> None:
            base = redirect.rsplit("/", 1)[0]
            try:
                urllib.request.urlopen(f"{base}/favicon.ico", timeout=5)
            except urllib.error.HTTPError:
                pass  # 404: not the callback path, server keeps waiting
            qs = urllib.parse.urlencode({"code": CODE, "state": state, "realmId": realm})
            urllib.request.urlopen(f"{redirect}?{qs}", timeout=5).read()

        threading.Thread(target=visit, daemon=True).start()
        return True

    return open_browser


def auth_settings() -> SimpleNamespace:
    return SimpleNamespace(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        realm_id=REALM,
        redirect_uri=f"http://127.0.0.1:{free_port()}/callback",
        env="sandbox",
    )


def test_auth_stores_the_refresh_token_and_leaks_nothing(capsys) -> None:
    events: list[str] = []
    conn = FakeConn(events)
    forms: list[dict] = []
    settings = auth_settings()
    auth.run_auth(
        conn,
        settings,
        token_post(events, forms=forms),
        open_browser=browser_that_consents(REALM),
        timeout_s=10,
    )
    assert forms == [
        {"grant_type": "authorization_code", "code": CODE, "redirect_uri": settings.redirect_uri}
    ]
    assert conn.stored == [NEW_RT]
    assert events == ["post", "store", "commit"]
    output = capsys.readouterr()
    assert all(s not in output.out + output.err for s in SENTINELS)
    assert "auth_refresh_token_stored" in output.out


def test_auth_stops_on_realm_mismatch_before_any_token_exchange(capsys) -> None:
    events: list[str] = []
    conn = FakeConn(events)
    with pytest.raises(auth.AuthError, match="REALM_ID"):
        auth.run_auth(
            conn,
            auth_settings(),
            token_post(events),
            open_browser=browser_that_consents("REALM-OF-ANOTHER-COMPANY"),
            timeout_s=10,
        )
    assert events == [] and conn.stored == []
    output = capsys.readouterr()
    assert all(s not in output.out + output.err for s in SENTINELS)


def test_auth_stops_on_forged_state(capsys) -> None:
    events: list[str] = []
    conn = FakeConn(events)
    with pytest.raises(auth.AuthError, match="state"):
        auth.run_auth(
            conn,
            auth_settings(),
            token_post(events),
            open_browser=browser_that_consents(REALM, state_override="forged-state"),
            timeout_s=10,
        )
    assert events == [] and conn.stored == []


# --- log hygiene ----------------------------------------------------------------------------


def test_refresh_retry_and_api_error_logs_carry_no_secret(capsys) -> None:
    events: list[str] = []
    tokens = auth.AccessTokens(FakeConn(events), token_post(events), now=lambda: T0)
    script = [429, 401, 400]

    def urlopen(request, timeout):
        status = script.pop(0)
        body = io.BytesIO(json.dumps({"Fault": {"Error": [{"Message": "bad", "code": "4000"}]}}).encode())
        headers = Message()
        headers["intuit_tid"] = "tid-123"
        raise urllib.error.HTTPError(request.full_url, status, "err", headers, body)

    client = QboClient("sandbox", REALM, tokens, urlopen=urlopen, sleep=lambda s: None, jitter=lambda: 0)
    with pytest.raises(QboApiError) as caught:
        client.query("select * from Invoice")
    output = capsys.readouterr()
    blob = output.out + output.err + str(caught.value)
    assert all(s not in blob for s in SENTINELS)
    assert "token_refreshed" in output.out and "api_retry" in output.out


def test_log_redacts_secret_named_fields(capsys) -> None:
    log("probe", refresh_token=NEW_RT, code=CODE, realm_id=REALM, client_secret=CLIENT_SECRET)
    line = json.loads(capsys.readouterr().out)
    assert line["refresh_token"] == "[redacted]" and line["realm_id"] == "[redacted]"
    assert all(s not in json.dumps(line) for s in SENTINELS)
