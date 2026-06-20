"""Integration: replay the real Canada 2024 race and check reality."""
import pytest

from backend.core.event_bus import EventBus
from backend.ingest.replay_engine import ReplayEngine


@pytest.fixture(scope="module")
def finished(canada):
    eng = ReplayEngine(canada, EventBus())
    eng.fast_forward(canada.duration_s)
    return eng


def test_final_podium_matches_reality(finished):
    rows = finished.state.leaderboard().rows
    assert [r.drv for r in rows[:3]] == ["VER", "NOR", "RUS"]


def test_final_lap_and_flag(finished):
    assert finished.state.lap == 70
    assert finished.state.flag == "CHEQUERED"


def test_everyone_pitted(finished):
    rows = finished.state.leaderboard().rows
    finishers = rows[:14]  # Canada had retirements; check the finishers
    assert all(r.pits >= 1 for r in finishers)
    assert all(r.compound is not None for r in rows)


def test_sc_actually_deployed_midrace(canada):
    eng = ReplayEngine(canada, EventBus())
    flags = []
    bus_pub = eng.bus.publish
    eng.bus.publish = lambda m: (flags.append(m.flag)
                                 if m.__class__.__name__ == "RaceControlMsg" else None)
    eng.t = 0.0
    eng._apply_until(canada.duration_s, emit=True)
    eng.bus.publish = bus_pub
    assert "SC" in flags, "Canada 2024 had safety cars; none derived"


def test_seek_back_and_forward(canada):
    eng = ReplayEngine(canada, EventBus())
    eng.fast_forward(3000)
    lap_at_3000 = eng.state.lap
    assert 10 < lap_at_3000 < 70
    eng.seek(500)
    assert eng.state.lap < lap_at_3000
    eng.seek(3000)
    assert eng.state.lap == lap_at_3000


def test_intervals_carry_lapped_strings(finished):
    rows = finished.state.leaderboard().rows
    tail_gaps = [r.gap_leader for r in rows if r.gap_leader]
    assert any("LAP" in g for g in tail_gaps), "expected lapped cars at flag"
