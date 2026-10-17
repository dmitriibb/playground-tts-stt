"""Event bus: model state changes, download progress, server errors and warnings.

Publishing is thread-safe (engines run in worker threads). Subscribers are
asyncio consumers, e.g. the `/ws/events` WebSocket in the gateway.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from typing import Any, Protocol

from pydantic import BaseModel, Field


class Event(BaseModel):
    seq: int = 0
    ts: float = Field(default_factory=time.time)
    type: str  # model.state | download.progress | log
    source: str  # stt | tts | gateway | common
    data: dict[str, Any] = Field(default_factory=dict)


class EventPublisher(Protocol):
    def publish(self, type: str, source: str, data: dict[str, Any]) -> None: ...


class EventBus:
    """In-process fan-out. When the modules become separate services, each one keeps
    its own bus and the gateway aggregates their event streams."""

    def __init__(self, subscriber_queue_size: int = 1000):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._seq = itertools.count(1)
        self._queue_size = subscriber_queue_size

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, type: str, source: str, data: dict[str, Any]) -> None:
        event = Event(seq=next(self._seq), type=type, source=source, data=data)
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._fan_out(event)
        else:
            loop.call_soon_threadsafe(self._fan_out, event)

    def _fan_out(self, event: Event) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                # Slow consumer: drop its oldest event rather than block everyone.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        self._subscribers.discard(queue)
