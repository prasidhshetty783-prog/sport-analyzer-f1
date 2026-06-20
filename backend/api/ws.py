"""WebSocket endpoint: broadcasts bus messages, accepts control commands."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from backend.api.schema import SelectSessionCmd, TransportCmd

router = APIRouter()
_CLIENT_MSG: TypeAdapter = TypeAdapter(TransportCmd | SelectSessionCmd)


@router.websocket("/ws")
async def ws_endpoint(socket: WebSocket) -> None:
    app = socket.app
    await socket.accept()
    queue = app.state.bus.subscribe()
    app.state.engine.snapshot()  # greet newcomer with full state

    async def pump_out() -> None:
        while True:
            msg = await queue.get()
            await socket.send_text(msg.model_dump_json())

    async def pump_in() -> None:
        while True:
            raw = await socket.receive_text()
            try:
                cmd = _CLIENT_MSG.validate_python(json.loads(raw))
            except (ValidationError, json.JSONDecodeError) as e:
                await socket.send_text(json.dumps(
                    {"kind": "error", "message": str(e)[:200]}))
                continue
            await handle_command(app, cmd)

    out_task = asyncio.create_task(pump_out())
    try:
        await pump_in()
    except WebSocketDisconnect:
        pass
    finally:
        out_task.cancel()
        app.state.bus.unsubscribe(queue)


async def handle_command(app, cmd) -> None:
    engine = app.state.engine
    if isinstance(cmd, TransportCmd):
        if cmd.action == "play":
            engine.play()
        elif cmd.action == "pause":
            engine.pause()
        elif cmd.action == "speed" and cmd.speed:
            engine.set_speed(cmd.speed)
        elif cmd.action == "seek" and cmd.seek_s is not None:
            engine.seek(cmd.seek_s)
    elif isinstance(cmd, SelectSessionCmd):
        await app.state.switch_session(cmd.session_id)
