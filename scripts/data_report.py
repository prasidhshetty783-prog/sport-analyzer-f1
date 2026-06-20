"""Phase 0 acceptance: one command that prints a data-availability report.

Runs every spike check (OpenF1, FastF1, Jolpica, Kaggle) plus replay-fixture
validation and prints a ✅/❌ scorecard. Exits nonzero if a required source
is down. Kaggle without credentials is a soft-skip (not needed until Phase 3).

Usage: python scripts/data_report.py [--skip-fastf1] [--skip-openf1-live-note]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from _common import FIXTURES_DIR, load_dotenv


def fixture_status() -> tuple[bool, str]:
    metas = sorted(FIXTURES_DIR.glob("*/meta.json"))
    if not metas:
        return False, "no fixture recorded — run: python scripts/record_fixture.py"
    import record_fixture

    lines = []
    all_ok = True
    for m in metas:
        meta = json.loads(m.read_text())
        ok, detail = record_fixture.validate(meta)
        all_ok &= ok
        lines.append(detail)
    return all_ok, " | ".join(lines)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--skip-fastf1", action="store_true",
                   help="skip the slow FastF1 session load")
    args = p.parse_args()

    load_dotenv()
    results: list[tuple[str, bool, str, bool]] = []  # name, ok, detail, required

    import check_openf1
    ok, detail = check_openf1.run()
    results.append(("OpenF1 REST (historical)", ok, detail, True))

    import check_jolpica
    ok, detail = check_jolpica.run()
    results.append(("Jolpica (Ergast successor)", ok, detail, True))

    if args.skip_fastf1:
        results.append(("FastF1", True, "SKIPPED by flag", False))
    else:
        import check_fastf1
        ok, detail = check_fastf1.run()
        results.append(("FastF1 (telemetry+weather)", ok, detail, True))

    import download_kaggle
    ok, detail = download_kaggle.run()
    results.append(("Kaggle datasets", ok, detail, False))

    ok, detail = fixture_status()
    results.append(("Replay fixture", ok, detail, True))

    token = bool(os.environ.get("OPENF1_TOKEN"))
    results.append(("OpenF1 live (paid token)", True,
                    "OPENF1_TOKEN set — live mode possible" if token
                    else "no OPENF1_TOKEN — replay mode only (expected for now)",
                    False))

    print("\n" + "=" * 70)
    print("PHASE 0 — DATA AVAILABILITY REPORT")
    print("=" * 70)
    hard_fail = False
    for name, ok, detail, required in results:
        mark = "✅" if ok else ("❌" if required else "⚠️ ")
        print(f"{mark} {name:<28} {detail}")
        if required and not ok:
            hard_fail = True
    print("=" * 70)
    print("Phase 0:", "FAILED — fix ❌ items above" if hard_fail else "PASSED")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
