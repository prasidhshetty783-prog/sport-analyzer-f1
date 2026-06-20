"""WS contract: snapshot on connect, transport commands honored."""
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.tests.conftest import CANADA, FIXTURES


@pytest.fixture(scope="module")
def client():
    if not (FIXTURES / CANADA / "meta.json").exists():
        pytest.skip("real fixture not present")
    app = create_app(FIXTURES)
    with TestClient(app) as c:
        yield c


def recv_kinds(ws, want=("session", "leaderboard"), n=12):
    """Read until all wanted kinds seen (paused engine sends a finite snapshot)."""
    out = {}
    for _ in range(n):
        m = json.loads(ws.receive_text())
        out.setdefault(m["kind"], m)
        if all(k in out for k in want):
            break
    return out


def test_sessions_endpoint(client):
    # listing is lightweight (meta.json only, no parquet load) so total_laps is
    # not populated here; the picker only needs session_id + name.
    rows = client.get("/api/sessions").json()
    assert any(s["session_id"] == CANADA and s["name"] for s in rows)


def test_snapshot_then_transport(client):
    with client.websocket_connect("/ws") as ws:
        kinds = recv_kinds(ws)
        assert "session" in kinds and "leaderboard" in kinds
        assert kinds["session"]["paused"] is True
        assert kinds["session"]["mode"] == "replay"

        ws.send_text(json.dumps({"kind": "transport", "action": "seek", "seek_s": 1800}))
        ws.send_text(json.dumps({"kind": "transport", "action": "play"}))
        ws.send_text(json.dumps({"kind": "transport", "action": "speed", "speed": 10}))
        seen_playing = False
        for _ in range(60):
            m = json.loads(ws.receive_text())
            if (m["kind"] == "session" and not m["paused"]
                    and m["t_s"] >= 1800 and m["speed"] == 10):
                seen_playing = True
                break
        assert seen_playing

        ws.send_text(json.dumps({"kind": "bogus"}))
        # malformed command answered with error, connection survives
        for _ in range(40):
            m = json.loads(ws.receive_text())
            if m["kind"] == "error":
                break
        ws.send_text(json.dumps({"kind": "transport", "action": "pause"}))


def test_session_opens_at_grid(client):
    with client.websocket_connect("/ws") as ws:
        kinds = recv_kinds(ws)
        s = kinds["session"]
        # default playhead sits just before lights out, not at data start
        assert s["t_s"] > 60, s["t_s"]
        assert s["paused"] is True
