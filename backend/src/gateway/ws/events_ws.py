"""WS /ws/events: model state changes, download progress, server errors and warnings."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from gateway.ws.common import SafeSender

router = APIRouter()


@router.websocket("/ws/events")
async def events(ws: WebSocket) -> None:
    from gateway.app import PROTOCOL_VERSION

    svc = ws.app.state.services
    await ws.accept()
    send = SafeSender(ws)
    queue = svc.bus.subscribe()
    await send.json({"type": "hello", "protocol": PROTOCOL_VERSION, "server_time": time.time()})

    async def pump() -> None:
        while True:
            event = await queue.get()
            await send.json(event.model_dump())  # type: model.state | download.progress | log
            if send.closed:
                return

    pump_task = asyncio.create_task(pump())
    try:
        while True:  # we only read to notice the disconnect (and answer pings)
            text = await ws.receive_text()
            if text == "ping":
                await send.json({"type": "pong", "server_time": time.time()})
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
        svc.bus.unsubscribe(queue)
