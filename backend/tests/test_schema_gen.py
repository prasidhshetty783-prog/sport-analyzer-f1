"""Generated TS types must be current (single-source schema discipline)."""
from pathlib import Path

from backend.api.gen_types import render

TYPES_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "ws" / "types.ts"


def test_types_ts_is_fresh():
    assert TYPES_TS.exists(), "run: python -m backend.api.gen_types"
    assert TYPES_TS.read_text(encoding="utf-8") == render()
