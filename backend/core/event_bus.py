"""Single internal event bus. Live ingest and replay are interchangeable
producers; WebSocket fan-out and (later) prediction workers are consumers."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel


class EventBus:
    def __init__(self, maxsize: int = 2000):
        self._maxsize = maxsize
        self._subs: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subs.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subs:
            self._subs.remove(q)

    def publish(self, msg: BaseModel) -> None:
        """Non-blocking fan-out; slow consumers lose oldest messages."""
        for q in self._subs:
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(msg)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)
