"""Batch-record EVERY race into data/fixtures/ — **host only**.

The Cowork/Claude sandbox blocks the OpenF1 domain (egress allowlist, see
CLAUDE.md), so this — like every data-fetching script — runs on the user's
machine. It enumerates all Race sessions for the given seasons via OpenF1 and
records each with `record_fixture.record_session`, skipping any fixture already
on disk so the job is fully resumable (interrupt and re-run any time).

OpenF1 only carries 2023→present, so that's the available universe of "all
races". Each race takes a few minutes to pull and is rate-limited; a full
multi-season sweep is a long but resumable job.

Usage (run from the repo root):
  python scripts/record_all.py                      # 2023..current, skip existing
  python scripts/record_all.py --seasons 2024 2025
  python scripts/record_all.py --limit 5            # just the next 5 missing
  python scripts/record_all.py --plan-only          # list what would be recorded
  python scripts/record_all.py --window-min 5 --fresh
"""
from __future__ import annotations

import argparse
import time
import traceback
from collections import Counter
from datetime import datetime, timezone

from _common import FIXTURES_DIR, hr, openf1_get
from record_fixture import record_session, validate


def list_races(seasons: list[int]) -> list[dict]:
    """Every Race session across the requested seasons, chronological."""
    races: list[dict] = []
    for year in seasons:
        try:
            sessions = openf1_get("sessions", year=year, session_name="Race")
        except Exception as e:  # noqa: BLE001
            print(f"  !! could not list {year} sessions: {e}", flush=True)
            continue
        for s in sessions:
            if s.get("session_type") == "Race":
                races.append(s)
    races.sort(key=lambda s: s.get("date_start") or "")
    return races


def slug_map(races: list[dict]) -> dict[int, str]:
    """Collision-safe slug per session_key. A country with one race in a season
    keeps the simple `{year}_{country}_race` form (matches existing fixtures);
    repeats (USA: Miami/Austin/Vegas) get a circuit suffix."""
    counts = Counter((s.get("year"), s.get("country_name")) for s in races)
    out: dict[int, str] = {}
    for s in races:
        year = int(s.get("year") or 0)
        country = (s.get("country_name") or "x").lower().replace(" ", "-")
        if counts[(s.get("year"), s.get("country_name"))] > 1:
            loc = (s.get("circuit_short_name") or s.get("location")
                   or s.get("session_key"))
            loc = str(loc).lower().replace(" ", "-")
            out[s["session_key"]] = f"{year}_{country}_{loc}_race"
        else:
            out[s["session_key"]] = f"{year}_{country}_race"
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    this_year = datetime.now(timezone.utc).year
    ap.add_argument("--seasons", type=int, nargs="+",
                    default=list(range(2023, this_year + 1)))
    ap.add_argument("--window-min", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0,
                    help="record at most N missing races this run (0 = no cap)")
    ap.add_argument("--fresh", action="store_true",
                    help="re-download every stream even if already on disk")
    ap.add_argument("--plan-only", action="store_true",
                    help="list what would be recorded and exit")
    args = ap.parse_args()

    hr(f"Enumerating Race sessions for seasons {args.seasons}")
    races = list_races(args.seasons)
    slugs = slug_map(races)
    if not races:
        print("No races found (is OpenF1 reachable from this machine?).")
        raise SystemExit(1)

    plan = []
    for s in races:
        slug = slugs[s["session_key"]]
        exists = (FIXTURES_DIR / slug / "meta.json").exists()
        plan.append((s, slug, exists))

    have = sum(1 for _, _, e in plan if e)
    todo = [(s, slug) for s, slug, e in plan if args.fresh or not e]
    if args.limit > 0:
        todo = todo[: args.limit]

    print(f"\n{len(races)} races total · {have} already recorded · "
          f"{len(todo)} to record this run\n")
    for s, slug, exists in plan:
        mark = "✓" if exists else " "
        flag = "(redo)" if exists and args.fresh else ""
        print(f"  [{mark}] {s.get('year')} {s.get('country_name'):<16} {slug} {flag}")
    if args.plan_only or not todo:
        print("\nplan-only / nothing to do." if args.plan_only else "\nAll recorded.")
        return

    results = []
    t0 = time.time()
    for i, (s, slug) in enumerate(todo, 1):
        hr(f"[{i}/{len(todo)}] {s.get('year')} {s.get('country_name')} -> {slug}")
        try:
            meta = record_session(s, "Race", args.window_min,
                                  resume=not args.fresh, slug=slug)
            ok, detail = validate(meta)
            results.append((slug, ok, detail))
            print(f"  {'✅' if ok else '❌'} {detail}", flush=True)
        except Exception as e:  # noqa: BLE001 - keep going to the next race
            results.append((slug, False, f"{type(e).__name__}: {e}"))
            print(f"  ❌ {slug} FAILED: {e}", flush=True)
            traceback.print_exc()

    ok_n = sum(1 for _, ok, _ in results if ok)
    hr(f"Batch done in {round(time.time() - t0)} s — "
       f"{ok_n}/{len(results)} ok")
    for slug, ok, detail in results:
        print(f"  {'✅' if ok else '❌'} {slug}: {detail}")
    raise SystemExit(0 if ok_n == len(results) else 1)


if __name__ == "__main__":
    main()
