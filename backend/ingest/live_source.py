"""Live data sources for Phase 5.

A `LiveSource` is the transport seam: it discovers the currently-live OpenF1
session, hands back the driver roster, and yields *new* rows per poll. The
`LiveClient` (see `live_client.py`) turns those rows into bus events via
`openf1_normalize`, so the rest of the app can't tell live from replay.

Two implementations:
  * `OpenF1RestSource` — authenticated incremental REST polling (the working
    path). Needs a paid `OPENF1_TOKEN`; honors the free-tier-style rate limit.
    The HTTP getter is injectable so tests never touch the network.
  * `OpenF1MqttSource` — a documented stub for the spec's *preferred* MQTT/WSS
    transport, to be filled in later. `make_live_source()` selects between them.

Hard rule (see [[Data Sources and Constraints]]): live needs the paid token; with
no token the app must stay replay-only — so the app never constructs a source
unless a token is present.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

OPENF1_BASE = "https://api.openf1.org/v1"

# How wide a window around a session's [start, end] still counts as "live"
# (formation/cool-down + broadcast delay slack).
LIVE_PRE_S = 15 * 60
LIVE_POST_S = 30 * 60

# Monotonic-by-`date` streams: a `date>` cursor pulls only rows newer than the
# last one seen — cheap and idempotent.
CURSOR_FIELD = {
    "location": "date",
    "car_data": "date",
    "intervals": "date",
    "position": "date",
    "pit": "date",
    "weather": "date",
    "race_control": "date",
}
# `laps` is special: a row appears at lap *start* (no duration) and the SAME row
# is later updated with `lap_duration` at lap *completion*. A date_start cursor
# would capture the start but never the finish time, so we refetch laps whole and
# rely on the state machine treating lap_start (max) / lap_done (set) as
# idempotent. `stints` has no timestamp at all — fetch all, dedupe new ones.


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class LiveSource(ABC):
    """Transport-agnostic live feed. `open()` latches the live session (or None);
    `poll()` returns new rows per endpoint since the last call."""

    @abstractmethod
    def open(self) -> dict | None:
        """Discover & latch the current live session. Returns the session dict
        (session_key, year, country_name, circuit_short_name, circuit_key,
        date_start, date_end, ...) or None if nothing is live right now."""

    @abstractmethod
    def drivers(self) -> list[dict]:
        """Driver roster rows for the latched session (after `open()`)."""

    @abstractmethod
    def poll(self) -> dict[str, list[dict]]:
        """New rows per streaming endpoint since the previous poll."""

    def total_laps_hint(self) -> int | None:
        """Best-effort scheduled lap count; None if unknown (OpenF1 doesn't
        broadcast it). The client falls back to circuit_facts / the live max."""
        return None

    def close(self) -> None:  # pragma: no cover - nothing to release by default
        pass


class OpenF1RestSource(LiveSource):
    """Authenticated incremental REST poller.

    Maintains a `date>` cursor per monotonic endpoint so each poll only pulls
    rows newer than the last one seen. The HTTP layer is injected (`http_get`)
    so the whole class is unit-testable offline; the default getter is built
    lazily and adds the Bearer token + rate limiting.
    """

    def __init__(self, token: str, *, http_get=None, base: str = OPENF1_BASE,
                 now_fn=_utcnow, session_name: str = "Race"):
        if not token and http_get is None:
            raise ValueError("OpenF1RestSource needs a token (live is paid)")
        self.token = token
        self.base = base
        self.now_fn = now_fn
        self.session_name = session_name
        self._http_get = http_get or self._default_get
        self.session: dict | None = None
        self.session_key: object = None
        self._roster: list[dict] = []
        self._cursor: dict[str, str] = {}
        self._seen_stints: set[tuple] = set()

    # -- discovery ---------------------------------------------------------

    def open(self) -> dict | None:
        """Latch the latest session if it's inside its live window."""
        rows = self._http_get("sessions", session_key="latest")
        sess = rows[0] if rows else None
        if not sess or not self._is_live(sess):
            self.session = None
            return None
        self.session = sess
        self.session_key = sess.get("session_key")
        self._roster = self._http_get("drivers", session_key=self.session_key)
        return sess

    def _is_live(self, sess: dict) -> bool:
        now = self.now_fn()
        start, end = _parse(sess.get("date_start")), _parse(sess.get("date_end"))
        if start is None:
            return False
        if now < start - timedelta(seconds=LIVE_PRE_S):
            return False
        if end is not None and now > end + timedelta(seconds=LIVE_POST_S):
            return False
        return True

    def drivers(self) -> list[dict]:
        return self._roster

    # -- polling -----------------------------------------------------------

    def poll(self) -> dict[str, list[dict]]:
        if self.session_key is None:
            return {}
        out: dict[str, list[dict]] = {}
        for ep, field in CURSOR_FIELD.items():
            params = {"session_key": self.session_key}
            cur = self._cursor.get(ep)
            if cur:
                params[f"{field}>"] = cur
            rows = self._http_get(ep, **params) or []
            if rows:
                newest = max((str(r.get(field)) for r in rows
                              if r.get(field) is not None), default=cur)
                if newest:
                    self._cursor[ep] = newest
            out[ep] = rows
        # laps: whole-session refetch (idempotent re-apply captures durations)
        out["laps"] = self._http_get("laps", session_key=self.session_key) or []
        out["stints"] = self._poll_stints()
        return out

    def _poll_stints(self) -> list[dict]:
        """Stints have no timestamp — fetch all, return only unseen
        (driver, stint_number) so re-applying never duplicates a stint."""
        rows = self._http_get("stints", session_key=self.session_key) or []
        fresh = []
        for r in rows:
            key = (r.get("driver_number"), r.get("stint_number"))
            if key not in self._seen_stints:
                self._seen_stints.add(key)
                fresh.append(r)
        return fresh

    # -- default authenticated HTTP getter (host only) ---------------------

    _last_req = 0.0
    _MIN_INTERVAL_S = 0.34  # gentle; OpenF1 live plans are higher-quota

    def _default_get(self, endpoint: str, **params) -> list:
        import requests  # lazy: tests inject http_get and never import this

        wait = self._MIN_INTERVAL_S - (time.monotonic() - OpenF1RestSource._last_req)
        if wait > 0:
            time.sleep(wait)
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        for attempt in range(5):
            OpenF1RestSource._last_req = time.monotonic()
            resp = requests.get(f"{self.base}/{endpoint}", params=params,
                                headers=headers, timeout=30)
            if resp.status_code == 404:
                return []  # OpenF1 returns 404 for an empty result set
            if resp.status_code == 429:
                time.sleep(min(2.0 * (attempt + 1), 8.0))
                continue
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        return []


class OpenF1MqttSource(LiveSource):  # pragma: no cover - documented stub
    """STUB — the spec's *preferred* MQTT-over-WSS transport, to fill in later.

    OpenF1's real-time plan publishes each endpoint as an MQTT topic (e.g.
    `v1/location`, `v1/car_data`, `v1/intervals`, ...) over WSS, authenticated
    with the same bearer token. To implement:

      1. Add an async MQTT client dep (e.g. `aiomqtt`) to requirements.
      2. In `open()`, connect to the broker (wss), authenticate, resolve the live
         session via REST `sessions?session_key=latest` (reuse OpenF1RestSource),
         and SUBSCRIBE to the per-endpoint topics.
      3. Buffer incoming messages into per-endpoint lists; `poll()` drains and
         returns the buffer (same shape as the REST source) so `LiveClient` is
         unchanged. No normalize/client changes needed — that's the whole point
         of this seam.

    Until then `open()` raises so misconfiguration fails loudly rather than
    silently degrading.
    """

    def __init__(self, token: str, **kw):
        self.token = token

    def open(self) -> dict | None:
        raise NotImplementedError(
            "MQTT live transport is a stub — use transport='rest' for now "
            "(see OpenF1MqttSource docstring for the fill-in plan).")

    def drivers(self) -> list[dict]:
        return []

    def poll(self) -> dict[str, list[dict]]:
        return {}


def make_live_source(transport: str = "rest", *, token: str, **kw) -> LiveSource:
    """Factory — the one line to swap transports. `rest` works today; `mqtt`
    is the documented hook (raises until implemented)."""
    t = (transport or "rest").lower()
    if t == "rest":
        return OpenF1RestSource(token, **kw)
    if t == "mqtt":
        return OpenF1MqttSource(token, **kw)
    raise ValueError(f"unknown live transport: {transport!r}")
