"""FastAPI app factory wiring store -> engine -> bus -> ws.

The engine is whichever producer is interchangeable on the bus: a `ReplayEngine`
for a recorded fixture, or a `LiveClient` for the live OpenF1 feed (Phase 5).
Live mode is gated on `OPENF1_TOKEN` — with no token the app never builds a live
source and stays strictly replay-only (hard constraint).
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import rest, ws
from backend.core.event_bus import EventBus
from backend.ingest.fixture_store import FixtureStore
from backend.ingest.live_client import LiveClient
from backend.ingest.live_source import make_live_source
from backend.ingest.replay_engine import ReplayEngine

DEFAULT_FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures"
LIVE_SESSION_ID = "live"


def create_app(fixtures_root: Path | None = None) -> FastAPI:
    root = Path(fixtures_root or os.environ.get("FIXTURES_DIR", DEFAULT_FIXTURES))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.bus = EventBus()
        app.state.store = FixtureStore(root)
        app.state._engine_task = None
        # Live mode is opt-in and paid: present only when a token exists.
        app.state.token = os.environ.get("OPENF1_TOKEN", "").strip()
        app.state.live_enabled = bool(app.state.token)
        app.state.live_transport = (
            os.environ.get("OPENF1_TRANSPORT", "rest").strip() or "rest")

        async def switch_session(session_id: str) -> None:
            if app.state._engine_task:
                app.state.engine.stop()
                app.state._engine_task.cancel()

            if session_id == LIVE_SESSION_ID:
                if not app.state.live_enabled:
                    # No token -> stay replay-only; never fabricate a live feed.
                    print("live requested but OPENF1_TOKEN unset; ignoring "
                          "(app stays replay-only)")
                    return
                source = make_live_source(app.state.live_transport,
                                          token=app.state.token)
                app.state.engine = LiveClient(source, app.state.bus)
                app.state._engine_task = asyncio.create_task(app.state.engine.run())
                return

            fixture = app.state.store.load(session_id)
            app.state.engine = ReplayEngine(fixture, app.state.bus)
            app.state._engine_task = asyncio.create_task(app.state.engine.run())
            # open on the grid (just before lights out), not in the garages;
            # scrubbing left still reaches the formation lap
            app.state.engine.seek(max(0.0, fixture.race_start_s - 15.0))

        app.state.switch_session = switch_session
        sessions = app.state.store.list_sessions()
        if sessions:
            await switch_session(sessions[0].session_id)
        elif app.state.live_enabled:
            # no fixtures recorded but a token is present -> boot straight to live
            await switch_session(LIVE_SESSION_ID)
        else:
            print(f"WARNING: no fixtures in {root} - record one with "
                  "scripts/record_fixture.py")
        yield
        if app.state._engine_task:
            app.state.engine.stop()
            app.state._engine_task.cancel()

    app = FastAPI(title="Sport Analyzer - F1 Live", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])
    app.include_router(rest.router)
    app.include_router(ws.router)
    return app


app = create_app()
