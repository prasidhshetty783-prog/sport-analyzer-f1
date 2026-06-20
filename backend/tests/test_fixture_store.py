"""Real-fixture loading: shapes, drivers, gaps, ordering."""


def test_loads_canada(canada):
    assert canada.total_laps == 70
    assert len(canada.drivers) == 20
    assert canada.duration_s > 5000  # ~1h52m of samples
    codes = {d.code for d in canada.drivers.values()}
    assert {"VER", "NOR", "RUS", "HAM"} <= codes


def test_events_sorted_and_typed(canada):
    ts = [e[0] for e in canada.events]
    assert ts == sorted(ts)
    kinds = {e[1] for e in canada.events}
    assert {"pos_frame", "car_tel", "interval", "position", "lap_start",
            "lap_done", "stint", "pit", "rc", "weather"} <= kinds


def test_gap_strings_parse_both_forms(canada):
    gaps = {e[2][1] for e in canada.events if e[1] == "interval" and e[2][1]}
    assert any(g.startswith("+") and "LAP" in g for g in gaps), "lapped-car gaps missing"
    numeric = [g for g in gaps if "LAP" not in g]
    assert numeric and all(float(g) >= 0 for g in numeric)


def test_pos_frames_cover_full_race(canada):
    frames = [e for e in canada.events if e[1] == "pos_frame"]
    assert len(frames) > 20000  # ~4 Hz for ~110 min
    # every frame's cars are (code,x,y,z) for known drivers
    sample = frames[len(frames) // 2]
    assert 15 <= len(sample[2]) <= 20


def test_no_zero_coordinates_in_pos_frames(canada):
    for t, kind, cars in canada.events:
        if kind == "pos_frame":
            assert all(not (c[1] == 0 and c[2] == 0) for c in cars), f"zero GPS at t={t}"


def test_race_start_detected(canada):
    # Canada 2024: lights out ~4 min after location data begins
    assert 180 < canada.race_start_s < 360, canada.race_start_s
