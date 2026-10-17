"""Helpers shared by the WebSocket endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from common.errors import AppError, ErrorCode

log = logging.getLogger("gateway.ws")


class SafeSender:
    """Serialises sends from several tasks; silently drops sends after the socket closed."""

    def __init__(self, ws: WebSocket):
        self._ws = ws
        self._lock = asyncio.Lock()
        self.closed = False

    async def json(self, message: dict[str, Any]) -> None:
        await self._send(text=json.dumps(message, ensure_ascii=False))

    async def bytes(self, data: bytes) -> None:
        await self._send(data=data)

    async def error(self, err: AppError, request_id: str | None) -> None:
        await self.json({"type": "error", "error": err.to_dict(request_id)})

    async def _send(self, text: str | None = None, data: bytes | None = None) -> None:
        if self.closed:
            return
        async with self._lock:
            try:
                if self._ws.client_state != WebSocketState.CONNECTED:
                    self.closed = True
                    return
                if text is not None:
                    await self._ws.send_text(text)
                else:
                    await self._ws.send_bytes(data or b"")
            except Exception:
                self.closed = True


def parse_json(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AppError(ErrorCode.INVALID_REQUEST, f"Invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or "type" not in data:
        raise AppError(ErrorCode.INVALID_REQUEST, "Message must be a JSON object with a 'type'")
    return data
