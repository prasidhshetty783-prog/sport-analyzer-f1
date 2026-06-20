"""Shared helpers for writing trained coefficients into the artifact priors.

The served models read ``models/artifacts/priors.json`` and merge any subset of
``{"compounds": {...}, "circuits": {...}}`` over the shipped defaults, so each
trainer can update its slice independently without a fragile model pickle.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "models" / "artifacts"
PRIORS_PATH = ARTIFACTS / "priors.json"


def load_priors() -> dict:
    try:
        return json.loads(PRIORS_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def merge_priors(section: str, values: dict) -> None:
    """Merge ``values`` into ``priors.json`` under ``section`` (compounds|circuits)."""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    pri = load_priors()
    pri.setdefault(section, {}).update(values)
    PRIORS_PATH.write_text(json.dumps(pri, indent=2, sort_keys=True))
    print(f"Updated {PRIORS_PATH} [{section}] with {len(values)} entries")
