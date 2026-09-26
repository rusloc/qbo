"""qbo_sync.client: URL shape, minorversion, 429 backoff + cap, 401 re-auth, throttle, Decimal parse."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from email.message import Message
from pathlib import Path

import pytest

from qbo_sync.client import (
    MAX_RETRIES,
    MIN_INTERVAL_S,
    QboApiError,
    QboClient,
    base_url,
    parse,
    server_time,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "qbo_api"
REALM = "REALM-SENTINEL-4620"


class FakeTokens:
    def __init__(self) -> None:
        self.value = "AT-SENTINEL-ONE"
        self.invalidations = 0

    def token(self) -> str:
        return self.value

    def invalidate(self) -> None:
        self.invalidations += 1
        self.value = "AT-SENTINEL-TWO"


class FakeHttp:
    """Scripted urlopen. Items: bytes -> 200 body; int -> HTTPError; (int, headers) -> HTTPError;
    Exception instance -> raised as is."""

    def __init__(self, script: list[object]) -> None:
        self.script = list(script)
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        item = self.script.pop(0)
        if isinstance(item, bytes):
            return io.BytesIO(item)
        if isinstance(item, Exception):
            raise item
        status, headers = item if isinstance(item, tuple) else (item, {})
        message = Message()
        for key, value in headers.items():
            message[key] = value
        body = json.dumps(
            {
                "Fault": {
                    "Error": [{"Message": "Something failed", "Detail": "detail", "code": "4000"}],
                    "type": "ValidationFault",
                }
            }
        ).encode()
        raise urllib.error.HTTPError(request.full_url, status, "error", message, io.BytesIO(body))


class Clock:
    """monotonic() + sleep() pair: sleeping advances the clock and is recorded."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(script, *, jitter=0.0, env="sandbox"):
    http = FakeHttp(script)
    clock = Clock()
    tokens = FakeTokens()
    client = QboClient(
        env,
        REALM,
        tokens,
        urlopen=http,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        jitter=lambda: jitter,
    )
    return client, http, clock, tokens


def test_query_url_is_sandbox_with_minorversion_75_and_json_accept() -> None:
    client, http, _, _ = make_client([b'{"QueryResponse": {}}'])
    client.query("select * from Invoice orderby Id startposition 1 maxresults 1000")
    request = http.requests[0]
    split = urllib.parse.urlsplit(request.full_url)
    params = urllib.parse.parse_qs(split.query)
    assert split.scheme == "https"
    assert split.hostname == "sandbox-quickbooks.api.intuit.com"
    assert split.path == f"/v3/company/{REALM}/query"
    assert params["minorversion"] == ["75"]
    assert params["query"] == ["select * from Invoice orderby Id startposition 1 maxresults 1000"]
    assert "+" not in split.query  # spaces sent as %20
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("Authorization") == "Bearer AT-SENTINEL-ONE"


def test_cdc_url_carries_entities_changed_since_and_minorversion() -> None:
    client, http, _, _ = make_client([b"{}"])
    client.cdc(["Invoice"], datetime(2026, 9, 25, 9, 50, 7, 999, tzinfo=UTC))
    split = urllib.parse.urlsplit(http.requests[0].full_url)
    params = urllib.parse.parse_qs(split.query)
    assert split.path.endswith("/cdc")
    assert params["entities"] == ["Invoice"]
    assert params["changedSince"] == ["2026-09-25T09:50:07+00:00"]
    assert params["minorversion"] == ["75"]


def test_prod_base_url_only_when_env_is_prod() -> None:
    assert base_url("sandbox") == "https://sandbox-quickbooks.api.intuit.com"
    assert base_url("prod") == "https://quickbooks.api.intuit.com"
    with pytest.raises(ValueError, match="sandbox"):
        base_url("production")


def test_429_backs_off_exponentially_then_succeeds() -> None:
    client, http, clock, _ = make_client([429, 429, b'{"ok": 1}'])
    assert client.query("select * from Bill") == '{"ok": 1}'
    assert clock.sleeps == [2.0, 4.0]
    assert len(http.requests) == 3


def test_429_retry_cap_is_five_retries_with_base_2s() -> None:
    client, http, clock, _ = make_client([429] * 10)
    with pytest.raises(QboApiError) as caught:
        client.query("select * from Bill")
    assert caught.value.status == 429
    assert clock.sleeps == [2.0, 4.0, 8.0, 16.0, 32.0]
    assert len(http.requests) == 1 + MAX_RETRIES


def test_backoff_adds_jitter_and_honours_larger_retry_after() -> None:
    client, _, clock, _ = make_client([(429, {"Retry-After": "10"}), 503, b"{}"], jitter=0.5)
    client.query("select * from Bill")
    assert clock.sleeps == [10.0, 5.0]  # max(2 + 1, 10), then 4 + 0.5 * 2


def test_network_errors_are_retried_then_reported() -> None:
    client, http, clock, _ = make_client([urllib.error.URLError("down")] * 6)
    with pytest.raises(QboApiError, match="network error"):
        client.query("select * from Bill")
    assert len(clock.sleeps) == MAX_RETRIES
    assert len(http.requests) == 6


def test_401_forces_one_token_refresh_then_repeats_the_call() -> None:
    client, http, clock, tokens = make_client([401, b"{}"])
    client.query("select * from Bill")
    assert tokens.invalidations == 1
    assert http.requests[1].get_header("Authorization") == "Bearer AT-SENTINEL-TWO"
    assert clock.sleeps == [MIN_INTERVAL_S]  # throttle only, no backoff


def test_second_401_is_not_retried_forever() -> None:
    client, http, _, _ = make_client([401, 401, b"{}"])
    with pytest.raises(QboApiError) as caught:
        client.query("select * from Bill")
    assert caught.value.status == 401
    assert len(http.requests) == 2


def test_400_fault_is_not_retried_and_message_has_no_realm_or_token(capsys) -> None:
    client, http, clock, _ = make_client([400])
    with pytest.raises(QboApiError) as caught:
        client.query("select * from Bill")
    message = str(caught.value)
    assert "HTTP 400" in message and "code 4000" in message
    assert REALM not in message and "AT-SENTINEL" not in message
    assert len(http.requests) == 1 and clock.sleeps == []
    output = capsys.readouterr()
    assert REALM not in output.out + output.err


def test_requests_are_spaced_to_stay_under_500_per_minute() -> None:
    client, _, clock, _ = make_client([b"{}", b"{}", b"{}"])
    for _ in range(3):
        client.query("select * from Class")
    assert clock.sleeps == [MIN_INTERVAL_S, MIN_INTERVAL_S]
    assert 60 / MIN_INTERVAL_S <= 500


def test_parse_keeps_money_exact_as_decimal() -> None:
    doc = parse((FIXTURES / "query_invoice_page.json").read_text(encoding="utf-8"))

    def walk(node: object) -> None:
        assert not isinstance(node, float)
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(doc)
    invoice = doc["QueryResponse"]["Invoice"][1]
    items = [line["Amount"] for line in invoice["Line"] if line["DetailType"] == "SalesItemLineDetail"]
    assert sum(items) == Decimal("0.30")
    assert invoice["TotalAmt"] == Decimal("0.27")


def test_server_time_is_converted_to_utc() -> None:
    assert server_time({"time": "2026-09-25T10:00:00.456-07:00"}) == datetime(
        2026, 9, 25, 17, 0, 0, 456000, tzinfo=UTC
    )
    assert server_time({}) is None
    assert server_time({"time": "not a time"}) is None
