"""Phase 0 spike: download the Kaggle training datasets into data/kaggle/.

Needs KAGGLE_USERNAME / KAGGLE_KEY (env or .env). If absent, prints manual
download URLs and exits 0 — per BUILD_PROMPT, this must not block Phase 0.

Usage: python scripts/download_kaggle.py
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

from _common import DATA_DIR, hr, load_dotenv

DATASETS = [
    ("rohanrao/formula-1-world-championship-1950-2020",
     "Full Ergast dump (results, lap_times, pit_stops, status...)"),
    ("cjgdev/formula-1-race-data-19502017",
     "Alternative Ergast-style dump (cross-check/backfill)"),
    ("alexjr2001/formula-1-dataset-race-data-and-telemetry",
     "FastF1-derived telemetry & lap aggregates"),
    ("mkaur1141/formula-1-world-championship-dataset-20002026",
     "Races/results/qualifying/standings through 2026"),
    ("dubradave/formula-1-drivers-dataset",
     "Driver career stats (skill prior)"),
]


def run() -> tuple[bool, str]:
    load_dotenv()
    hr("Kaggle datasets")
    out_root = DATA_DIR / "kaggle"
    out_root.mkdir(parents=True, exist_ok=True)

    have_creds = bool(os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY")) \
        or (Path.home() / ".kaggle" / "kaggle.json").exists()

    if not have_creds:
        print("\nNo Kaggle credentials found (KAGGLE_USERNAME/KAGGLE_KEY or ~/.kaggle/kaggle.json).")
        print("Manual download — place extracted CSVs under data/kaggle/<dataset-name>/ :\n")
        for slug, why in DATASETS:
            print(f"  https://www.kaggle.com/datasets/{slug}")
            print(f"      → data/kaggle/{slug.split('/')[1]}/   ({why})")
        return True, "SKIPPED — no credentials; manual URLs printed (not needed until Phase 3)"

    try:
        from kaggle.api.kaggle_api_extended import KaggleApi

        api = KaggleApi()
        api.authenticate()
        done = []
        for slug, _ in DATASETS:
            name = slug.split("/")[1]
            dest = out_root / name
            if dest.exists() and any(dest.iterdir()):
                print(f"  {name}: already present, skipping")
                done.append(name)
                continue
            dest.mkdir(parents=True, exist_ok=True)
            print(f"  downloading {slug} ...")
            api.dataset_download_files(slug, path=str(dest), unzip=False, quiet=True)
            for z in dest.glob("*.zip"):
                with zipfile.ZipFile(z) as zf:
                    zf.extractall(dest)
                z.unlink()
            done.append(name)
        return True, f"Downloaded/present: {', '.join(done)}"
    except Exception as e:  # noqa: BLE001
        return False, f"Kaggle download failed: {e}"


if __name__ == "__main__":
    ok, detail = run()
    print(f"\n{'✅' if ok else '❌'} {detail}")
    raise SystemExit(0 if ok else 1)
