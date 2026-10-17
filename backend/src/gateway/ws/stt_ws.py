"""WS /ws/stt: one live STT session per connection.

C->S  {"type":"start", ...LiveStartOptions}
S->C  {"type":"ready","session_id",...}
C->S  binary frames: 4-byte little-endian seq + PCM s16le 16 kHz mono
S->C  vad / transcript.partial / transcript.final
C->S  {"type":"end_input"} | {"type":"cancel"}
S->C  {"type":"session.completed","metrics":{...}} | {"type":"error",...}
"""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from common.errors import AppError, ErrorCode
from gateway.ws.common import SafeSender, parse_json
from stt.schemas import LiveStartOptions

router = APIRouter()
log = logging.getLogger("gateway.ws.stt")


@router.websocket("/ws/stt")
async def stt_stream(ws: WebSocket) -> None:
    from gateway.app import PROTOCOL_VERSION

    svc = ws.app.state.services
    await ws.accept()
    send = SafeSender(ws)
    session_id = uuid.uuid4().hex[:12]
    handle = None
    expected_seq = 0
    gaps = 0
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            try:
                if msg.get("bytes") is not None:
                    data: bytes = msg["bytes"]
                    if handle is None:
                        raise AppError(ErrorCode.INVALID_REQUEST, "Send 'start' before audio")
                    if len(data) < 4:
                        raise AppError(ErrorCode.INVALID_AUDIO, "Frame shorter than the 4-byte header")
                    seq = int.from_bytes(data[:4], "little")
                    if seq != expected_seq:
                        gaps += 1
                        log.warning("Session %s: frame seq %d, expected %d", session_id, seq, expected_seq,
                                    extra={"session_id": session_id, "request_id": session_id})
                    expected_seq = seq + 1
                    handle.feed_pcm16(data[4:])
                    continue
                data_json = parse_json(msg.get("text") or "")
                kind = data_json["type"]
                if kind == "start":
                    if handle is not None:
                        raise AppError(ErrorCode.INVALID_REQUEST, "Session already started")
                    try:
                        opts = LiveStartOptions.model_validate(data_json)
                    except ValidationError as exc:
                        raise AppError(ErrorCode.INVALID_REQUEST, "Invalid start message",
                                       {"errors": exc.errors(include_context=False)}) from exc
                    handle = await svc.stt.open_live_session(opts, send.json, session_id)
                    await send.json({"type": "ready", "session_id": session_id, "protocol": PROTOCOL_VERSION,
                                     "model_id": opts.model_id, "mode": opts.mode, "device": handle.device,
                                     "server_time": time.time()})
                elif kind == "end_input":
                    if handle is None:
                        raise AppError(ErrorCode.INVALID_REQUEST, "No active session")
                    handle.end_input()
                elif kind == "cancel":
                    if handle is not None:
                        await handle.cancel()
                    await send.json({"type": "cancelled", "session_id": session_id})
                    break
                elif kind == "ping":
                    await send.json({"type": "pong", "server_time": time.time()})
                else:
                    raise AppError(ErrorCode.INVALID_REQUEST, f"Unknown message type {kind!r}")
            except AppError as exc:
                await send.error(exc, session_id)
    except WebSocketDisconnect:
        pass
    finally:
        if handle is not None:
            await handle.cancel()
        if gaps:
            log.info("Session %s ended with %d sequence gaps", session_id, gaps)
