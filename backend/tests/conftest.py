import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

FIXTURES = Path(os.environ.get(
    "FIXTURES_DIR",
    Path(__file__).resolve().parents[2] / "data" / "fixtures"))
CANADA = "2024_canada_race"


@pytest.fixture(scope="session")
def canada():
    from backend.ingest.fixture_store import load_fixture

    path = FIXTURES / CANADA
    if not (path / "meta.json").exists():
        pytest.skip(f"real fixture not present at {path}")
    return load_fixture(path)
