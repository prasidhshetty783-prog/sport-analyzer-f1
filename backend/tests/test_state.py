"""Unit tests for the flag state machine and tyre bookkeeping."""
from backend.state.race_state import RaceState


class _FX:  # minimal fixture stub
    class _D:
        def __init__(self, n, c):
            self.number, self.code, self.team, self.colour = n, c, "T", "ffffff"
    drivers = {1: _D(1, "VER"), 44: _D(44, "HAM")}


def make_state():
    return RaceState(_FX())


def test_sc_lifecycle():
    s = make_state()
    assert s.flag == "GREEN"
    s.apply("rc", ("SafetyCar", None, None, "SAFETY CAR DEPLOYED"))
    assert s.flag == "SC"
    s.apply("rc", ("SafetyCar", None, None, "SAFETY CAR IN THIS LAP"))
    assert s.flag == "SC"  # still out until green
    s.apply("rc", ("Flag", "GREEN", "Track", "GREEN LIGHT"))
    assert s.flag == "GREEN"


def test_red_overrides_everything():
    s = make_state()
    s.apply("rc", ("SafetyCar", None, None, "SAFETY CAR DEPLOYED"))
    s.apply("rc", ("Flag", "RED", "Track", "RED FLAG"))
    assert s.flag == "RED"
    s.apply("rc", ("Flag", "GREEN", "Track", "GREEN LIGHT"))
    assert s.flag == "GREEN"


def test_sector_yellow_clear():
    s = make_state()
    s.apply("rc", ("Flag", "YELLOW", "Sector", "YELLOW IN SECTOR 3"))
    assert s.flag == "YELLOW"
    s.apply("rc", ("Flag", "CLEAR", "Sector", "CLEAR IN SECTOR 3"))
    assert s.flag == "GREEN"


def test_chequered_terminal_but_below_red():
    s = make_state()
    s.apply("rc", ("Flag", "CHEQUERED", "Track", "CHEQUERED FLAG"))
    assert s.flag == "CHEQUERED"


def test_tyre_age_tracks_stints():
    s = make_state()
    s.apply("stint", (1, 1, "INTERMEDIATE", 1, 25, 0))
    s.apply("stint", (1, 2, "MEDIUM", 26, 70, 0))
    s.apply("lap_start", (1, 10))
    assert s.cars[1].tyre() == ("INTERMEDIATE", 9)
    s.apply("lap_start", (1, 30))
    assert s.cars[1].tyre() == ("MEDIUM", 4)


def test_leaderboard_orders_and_hides_leader_gap():
    s = make_state()
    s.apply("position", (44, 1))
    s.apply("position", (1, 2))
    s.apply("interval", (1, "1.234", "1.234"))
    s.apply("interval", (44, "0.0", "0.0"))
    lb = s.leaderboard()
    assert [r.drv for r in lb.rows] == ["HAM", "VER"]
    assert lb.rows[0].gap_leader is None
    assert lb.rows[1].gap_leader == "1.234"
