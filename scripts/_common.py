"""Shared helpers for Phase 0 data-access spike scripts."""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
FIXTURES_DIR = DATA_DIR / "fixtures"

OPENF1_BASE = "https://api.openf1.org/v1"
JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"

# OpenF1 free tier ~= 3 req/s burst, but sustained pulls hit a quota wall
# (~80 fast requests -> persistent 429, observed June 2026). Pace gently.
MIN_REQUEST_INTERVAL_S = 0.60
_last_request_at = 0.0


def load_dotenv() -> None:
    """Load .env if python-dotenv is available; never fail."""
    try:
        from dotenv import load_dotenv as _ld

        _ld(REPO_ROOT / ".env")
    except Exception:
        pass


def http_get_json(url: str, params: dict | None = None, *, retries: int = 7,
                  timeout: int = 60) -> list | dict:
    """Rate-limited GET with patient retry/backoff. Raises on final failure.

    429s are waited out (Retry-After honored, else exponential up to 60 s) —
    OpenF1's quota recovers if you stand still for a minute.
    """
    global _last_request_at
    last_err: object = None
    for attempt in range(retries):
        wait = MIN_REQUEST_INTERVAL_S - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        try:
            _last_request_at = time.monotonic()
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 429:
                delay = max(float(resp.headers.get("Retry-After") or 0),
                            min(8.0 * (2 ** attempt), 60.0))
                last_err = f"429 rate-limited on attempt {attempt + 1}"
                print(f"    .. rate-limited, waiting {delay:.0f}s", flush=True)
                time.sleep(delay)
                continue
            if resp.status_code == 404:
                # OpenF1 returns 404 when no rows match the query (e.g. a date
                # window after the session's data ends) — observed June 2026.
                return []
            resp.raise_for_status()
            return resp.json()
        except Exception as e:  # noqa: BLE001 - spike script, report at end
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_err}")


def openf1_get(endpoint: str, **params) -> list:
    """GET an OpenF1 endpoint. Historical data needs no auth."""
    out = http_get_json(f"{OPENF1_BASE}/{endpoint}", params=params)
    if not isinstance(out, list):
        raise RuntimeError(f"OpenF1 {endpoint}: expected list, got {type(out)}")
    return out


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "+00:00")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def date_windows(start: datetime, end: datetime, minutes: int):
    """Yield (window_start, window_end) covering [start, end]."""
    cur = start
    step = timedelta(minutes=minutes)
    while cur < end:
        nxt = min(cur + step, end)
        yield cur, nxt
        cur = nxt


def resolve_session(year: int, country: str, session_name: str = "Race") -> dict:
    """Find an OpenF1 session by year + country name + session name."""
    sessions = openf1_get("sessions", year=year, session_name=session_name)
    matches = [s for s in sessions
               if country.lower() in (s.get("country_name") or "").lower()
               or country.lower() in (s.get("circuit_short_name") or "").lower()
               or country.lower() in (s.get("location") or "").lower()]
    if not matches:
        available = sorted({s.get("country_name") for s in sessions})
        raise RuntimeError(
            f"No {year} '{session_name}' session matching '{country}'. "
            f"Available: {available}")
    return matches[0]


def hr(title: str) -> None:
    print(f"\n{'=' * 62}\n{title}\n{'=' * 62}")


def sample_rows(rows: list, n: int = 3) -> str:
    import json

    return "\n".join(json.dumps(r, default=str) for r in rows[:n])


def fail(msg: str) -> None:
    print(f"❌ {msg}")
    sys.exit(1)
