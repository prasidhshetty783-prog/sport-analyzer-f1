"""Phase 0: record one full historical race from OpenF1 into data/fixtures/.

Pulls every stream the app needs (location, car_data, position, intervals,
laps, stints, pit, weather, race_control, drivers + session/meeting metadata)
via chunked, rate-limited historical REST calls (no auth needed) and writes
one Parquet file per stream plus meta.json. The Phase 1 replay engine re-emits
these through the internal event bus.

High-frequency streams (location ~3.7 Hz × 20 cars, car_data likewise) are
fetched in date windows to keep responses small and respect the rate limit.
A full race takes a few minutes to record. Re-running resumes at both stream
and window level: anything already on disk is skipped (--fresh re-downloads
everything). Persistent 429s are waited out, not treated as failures.

Usage:
  python scripts/record_fixture.py [--year 2024] [--country Canada]
                                   [--session Race] [--window-min 4] [--fresh]
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone

import pandas as pd

from _common import (FIXTURES_DIR, date_windows, hr, iso, openf1_get,
                     parse_iso, resolve_session)

# stream -> sort columns
SIMPLE_STREAMS = {
    "drivers": ["driver_number"],
    "laps": ["date_start", "driver_number"],
    "stints": ["driver_number", "stint_number"],
    "pit": ["date", "driver_number"],
    "position": ["date", "driver_number"],
    "race_control": ["date"],
    "weather": ["date"],
}
CHUNKED_STREAMS = {
    "location": ["date", "driver_number"],
    "car_data": ["date", "driver_number"],
    "intervals": ["date", "driver_number"],
}


def fetch_chunked(endpoint: str, skey: int, start: datetime, end: datetime,
                  window_min: int, parts_dir) -> pd.DataFrame:
    """Windowed fetch with per-window persistence: every completed window is
    saved to parts_dir immediately, so a crash/rate-limit never loses work —
    the next run skips windows already on disk."""
    parts_dir.mkdir(parents=True, exist_ok=True)
    frames, n_win = [], 0
    for ws, we in date_windows(start, end, window_min):
        n_win += 1
        part = parts_dir / f"{endpoint}_{n_win:03d}.parquet"
        if part.exists():
            df = pd.read_parquet(part)
            print(f"    {endpoint}: window {n_win} -> {len(df)} rows (cached)",
                  flush=True)
            if not df.empty:
                frames.append(df)
            continue
        rows = openf1_get(endpoint, session_key=skey,
                          **{"date>": iso(ws), "date<": iso(we)})
        df = sanitize(pd.DataFrame(rows))
        df.to_parquet(part, index=False)
        if not df.empty:
            frames.append(df)
        print(f"    {endpoint}: window {n_win} ({iso(ws)[11:19]}-{iso(we)[11:19]}) "
              f"-> {len(rows)} rows", flush=True)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def existing_rows(path) -> int:
    """Row count of an existing parquet without loading it (0 if absent/broken)."""
    try:
        import pyarrow.parquet as pq

        return pq.ParquetFile(path).metadata.num_rows
    except Exception:  # noqa: BLE001
        return 0


def record(year: int, country: str, session_name: str, window_min: int,
           resume: bool = True) -> dict:
    """Resolve a session by year+country+name, then record it."""
    session = resolve_session(year, country, session_name)
    return record_session(session, session_name, window_min, resume)


def default_slug(session: dict, session_name: str = "Race") -> str:
    year = int(session.get("year") or 0)
    country = (session.get("country_name") or "x").lower().replace(" ", "-")
    return f"{year}_{country}_{session_name.lower()}"


def record_session(session: dict, session_name: str = "Race", window_min: int = 4,
                   resume: bool = True, slug: str | None = None) -> dict:
    """Record an already-resolved OpenF1 session dict into data/fixtures/.

    Taking the session directly (rather than re-resolving by country) lets the
    batch recorder disambiguate multi-race countries (USA: Miami/Austin/Vegas)
    and pass a collision-safe slug.
    """
    year = int(session.get("year") or 0)
    skey = session["session_key"]
    meeting = openf1_get("meetings", meeting_key=session["meeting_key"])
    meeting = meeting[0] if meeting else {}

    if slug is None:
        slug = default_slug(session, session_name)
    out = FIXTURES_DIR / slug
    out.mkdir(parents=True, exist_ok=True)

    hr(f"Recording fixture: {meeting.get('meeting_official_name', slug)} "
       f"(session_key={skey}) -> data/fixtures/{slug}/")

    start = parse_iso(session["date_start"]) - timedelta(minutes=2)
    end = parse_iso(session["date_end"]) + timedelta(minutes=2)
    print(f"  window: {iso(start)} -> {iso(end)}", flush=True)

    summary: dict[str, int] = {}
    errors: dict[str, str] = {}
    t0 = time.time()

    def save_stream(ep: str, sort_cols: list[str], fetch) -> None:
        path = out / f"{ep}.parquet"
        if resume:
            n = existing_rows(path)
            if n > 0:
                summary[ep] = n
                print(f"  {ep}: {n} rows (already recorded, skipping)", flush=True)
                return
        try:
            df = tidy(fetch(), sort_cols)
            df.to_parquet(path, index=False)
            summary[ep] = len(df)
            print(f"  {ep}: {len(df)} rows", flush=True)
        except Exception as e:  # noqa: BLE001 - keep recording other streams
            import traceback

            summary[ep] = 0
            errors[ep] = f"{type(e).__name__}: {e}"
            print(f"  !! {ep} FAILED: {errors[ep]}", flush=True)
            traceback.print_exc()

    def fetch_laps() -> pd.DataFrame:
        """Whole-session laps; falls back to per-driver queries if that fails
        or comes back empty (big unfiltered laps queries can be flaky)."""
        rows: list = []
        try:
            rows = openf1_get("laps", session_key=skey)
        except Exception as e:  # noqa: BLE001
            print(f"    laps: whole-session query failed ({e}); trying per-driver",
                  flush=True)
        if not rows:
            for d in openf1_get("drivers", session_key=skey):
                r = openf1_get("laps", session_key=skey,
                               driver_number=d["driver_number"])
                print(f"    laps: driver {d['driver_number']} -> {len(r)} rows",
                      flush=True)
                rows.extend(r)
        return pd.DataFrame(rows)

    for ep, sort_cols in SIMPLE_STREAMS.items():
        if ep == "laps":
            save_stream(ep, sort_cols, fetch_laps)
        else:
            save_stream(ep, sort_cols,
                        lambda ep=ep: pd.DataFrame(openf1_get(ep, session_key=skey)))

    parts_dir = out / "_parts"
    for ep, sort_cols in CHUNKED_STREAMS.items():
        save_stream(ep, sort_cols,
                    lambda ep=ep: fetch_chunked(ep, skey, start, end,
                                                window_min, parts_dir))
        if ep not in errors and (out / f"{ep}.parquet").exists():
            for p in parts_dir.glob(f"{ep}_*.parquet"):
                p.unlink()

    meta = {
        "fixture_version": 1,
        "source": "openf1-historical-rest",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "session": session,
        "meeting": meeting,
        "streams": summary,
        "errors": errors,
        "elapsed_s": round(time.time() - t0, 1),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str))
    print(f"\n  done in {meta['elapsed_s']} s"
          + (f" — {len(errors)} stream(s) FAILED: {sorted(errors)}" if errors else ""),
          flush=True)
    return meta


def sanitize(df: pd.DataFrame) -> pd.DataFrame:
    """Make mixed-type object columns parquet-safe.

    OpenF1 mixes floats and strings in some fields (intervals gap_to_leader /
    interval: 3.2 vs '+1 LAP' for lapped cars) — pyarrow refuses those.
    Pure-numeric object cols -> float; mixed scalar cols -> string with nulls
    preserved; nested cols (laps segments_sector_*) left alone.
    """
    for col in df.columns:
        if df[col].dtype != object:
            continue
        vals = df[col].dropna()
        if vals.empty:
            continue
        if vals.map(lambda v: isinstance(v, (list, dict, tuple))).any():
            continue
        num = pd.to_numeric(vals, errors="coerce")
        if num.notna().all():
            df[col] = pd.to_numeric(df[col], errors="coerce")
        elif not vals.map(lambda v: isinstance(v, str)).all():
            df[col] = df[col].map(lambda v: None if pd.isna(v) else str(v))
    return df


def tidy(df: pd.DataFrame, sort_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return df
    df = sanitize(df)
    # drop_duplicates chokes on unhashable cells (laps segments_sector_* are
    # lists) — dedupe on the hashable columns only.
    hashable = [c for c in df.columns
                if not df[c].map(lambda v: isinstance(v, (list, dict))).any()]
    if hashable:
        df = df.drop_duplicates(subset=hashable)
    cols = [c for c in sort_cols if c in df.columns]
    if cols:
        df = df.sort_values(cols, kind="stable").reset_index(drop=True)
    return df


REQUIRED_NONEMPTY = ["drivers", "laps", "stints", "position", "weather",
                     "location", "car_data", "intervals"]


def validate(meta: dict) -> tuple[bool, str]:
    missing = [s for s in REQUIRED_NONEMPTY if meta["streams"].get(s, 0) == 0]
    name = meta["session"].get("country_name", "?")
    year = meta["session"].get("year", "?")
    total = sum(meta["streams"].values())
    if missing:
        return False, f"{year} {name}: empty streams {missing}"
    return True, (f"{year} {name} Race: {total:,} rows across "
                  f"{len(meta['streams'])} streams "
                  f"(location={meta['streams']['location']:,}, "
                  f"car_data={meta['streams']['car_data']:,})")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int, default=2024)
    p.add_argument("--country", default="Canada")
    p.add_argument("--session", default="Race")
    p.add_argument("--window-min", type=int, default=4)
    p.add_argument("--fresh", action="store_true",
                   help="re-download everything (ignore already-recorded streams)")
    a = p.parse_args()
    meta = record(a.year, a.country, a.session, a.window_min, resume=not a.fresh)
    ok, detail = validate(meta)
    print(f"\n{'✅' if ok else '❌'} {detail}")
    raise SystemExit(0 if ok else 1)
