"""HTTP client for the QBO Accounting API v3 (spec §1 hard constraints).

- Base URL: sandbox unless ENV=prod. `minorversion=75` is appended to every call.
- One request at a time (the 10-concurrent cap holds trivially); request starts are spaced
  60/480 s apart, so a realm never sees more than 480 req/min (limit 500).
- HTTP 429, 5xx and network errors: exponential backoff, base 2 s, at most 5 retries, jitter;
  a larger Retry-After wins. HTTP 401: one forced token refresh, then the call is repeated.
- Responses come back as raw text. Callers land that text unchanged (db.land_raw) and read it
  only through `parse()`, which turns JSON numbers into Decimal, never float.
- The request URL contains the realmId, so it is never logged or put in an exception message.
"""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from qbo_sync.jsonlog import log

BASE_URLS = {
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
    "prod": "https://quickbooks.api.intuit.com",
}
MINOR_VERSION = "75"
MAX_RESULTS = 1000  # QBO query page cap
MAX_RETRIES = 5
BACKOFF_BASE_S = 2.0
MIN_INTERVAL_S = 60 / 480
TIMEOUT_S = 60
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
USER_AGENT = "qbo-pnl-qbo_sync/1.0"


class QboApiError(Exception):
    """A QBO API call failed for good. The message names the resource, never the URL."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class TokenSource(Protocol):
    def token(self) -> str: ...

    def invalidate(self) -> None: ...


def base_url(env: str) -> str:
    try:
        return BASE_URLS[env]
    except KeyError:
        raise ValueError(f"ENV must be 'sandbox' or 'prod', got {env!r}") from None


def parse(text: str) -> dict[str, Any]:
    """Parse a QBO JSON response. Fractional numbers become Decimal, never float."""
    return json.loads(text, parse_float=Decimal)


def utcnow() -> datetime:
    return datetime.now(UTC)


def server_time(doc: Mapping[str, Any]) -> datetime | None:
    """The response's top-level `time` (QBO server clock, local offset) as UTC, if present."""
    value = doc.get("time")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError:
        return None


def _fault_summary(err: urllib.error.HTTPError) -> str:
    """First error code + message of a QBO Fault body, shortened. Empty if not parseable."""
    try:
        doc = json.loads(err.read().decode("utf-8", errors="replace"))
    except (ValueError, OSError):
        return ""
    fault = doc.get("Fault") or doc.get("fault") or {}
    errors = fault.get("Error") or fault.get("error") or []
    if not errors or not isinstance(errors[0], dict):
        return ""
    first = errors[0]
    code = first.get("code", "")
    message = first.get("Message") or first.get("message") or ""
    detail = first.get("Detail") or first.get("detail") or ""
    return f"code {code}: {message} {detail}".strip()[:300]


class QboClient:
    """Sequential, rate-limited GET client for one realm."""

    def __init__(
        self,
        env: str,
        realm_id: str,
        tokens: TokenSource,
        *,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._company_url = f"{base_url(env)}/v3/company/{urllib.parse.quote(realm_id, safe='')}"
        self._tokens = tokens
        self._urlopen = urlopen
        self._sleep = sleep
        self._monotonic = monotonic
        self._jitter = jitter
        self._last_start: float | None = None

    def query(self, statement: str) -> str:
        return self.get("query", {"query": statement})

    def cdc(self, entities: Sequence[str], changed_since: datetime) -> str:
        return self.get(
            "cdc",
            {
                "entities": ",".join(entities),
                "changedSince": changed_since.astimezone(UTC).isoformat(timespec="seconds"),
            },
        )

    def get(self, resource: str, params: Mapping[str, str]) -> str:
        """GET <company>/<resource>?<params>&minorversion=75 and return the body text."""
        query = urllib.parse.urlencode(
            {**params, "minorversion": MINOR_VERSION}, quote_via=urllib.parse.quote
        )
        url = f"{self._company_url}/{resource}?{query}"
        retries = 0
        reauthorized = False
        while True:
            self._throttle()
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._tokens.token()}",
                    "User-Agent": USER_AGENT,
                },
            )
            try:
                with self._urlopen(request, timeout=TIMEOUT_S) as response:
                    return response.read().decode("utf-8")
            except urllib.error.HTTPError as err:
                status = err.code
                intuit_tid = err.headers.get("intuit_tid") if err.headers else None
                if status == 401 and not reauthorized:
                    reauthorized = True
                    self._tokens.invalidate()
                    log("api_unauthorized_refreshing", "warning", resource=resource)
                    continue
                if status in RETRYABLE_STATUS and retries < MAX_RETRIES:
                    retries += 1
                    retry_after = err.headers.get("Retry-After") if err.headers else None
                    self._backoff(resource, retries, status, intuit_tid, retry_after)
                    continue
                summary = _fault_summary(err)
                raise QboApiError(
                    f"{resource}: HTTP {status} after {retries} retries"
                    f"{'; ' + summary if summary else ''}"
                    f"{'; intuit_tid ' + intuit_tid if intuit_tid else ''}",
                    status=status,
                ) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
                if retries < MAX_RETRIES:
                    retries += 1
                    self._backoff(resource, retries, None, None, None, type(err).__name__)
                    continue
                raise QboApiError(
                    f"{resource}: network error ({type(err).__name__}) after {retries} retries"
                ) from None

    def _throttle(self) -> None:
        now = self._monotonic()
        if self._last_start is not None:
            wait = self._last_start + MIN_INTERVAL_S - now
            if wait > 0:
                self._sleep(wait)
                now += wait
        self._last_start = now

    def _backoff(
        self,
        resource: str,
        attempt: int,
        status: int | None,
        intuit_tid: str | None,
        retry_after: str | None,
        error_type: str | None = None,
    ) -> None:
        delay = BACKOFF_BASE_S * 2 ** (attempt - 1) + self._jitter() * BACKOFF_BASE_S
        if retry_after and retry_after.strip().isdigit():
            delay = max(delay, float(retry_after))
        log(
            "api_retry",
            "warning",
            resource=resource,
            attempt=attempt,
            max_retries=MAX_RETRIES,
            status=status,
            error_type=error_type,
            intuit_tid=intuit_tid,
            delay_s=round(delay, 2),
        )
        self._sleep(delay)
