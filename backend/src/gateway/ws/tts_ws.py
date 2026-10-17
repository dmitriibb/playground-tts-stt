"""WS /ws/tts: one streaming synthesis per `start` message.

C->S  {"type":"start","model_id","text","voice","language","speed"}
S->C  {"type":"audio.meta","sample_rate","format":"pcm_s16le","streaming_kind","segments",...}
S->C  {"type":"segment","index","text","audio_ms","timings"} followed by
      binary: 4-byte little-endian seq + PCM s16le
S->C  {"type":"done","metrics":{...}}
C->S  {"type":"cancel"} at any time
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from common.errors import AppError, ErrorCode, wrap_exception
from gateway.ws.common import SafeSender, parse_json
from tts.schemas import TtsStreamStart

router = APIRouter()
log = logging.getLogger("gateway.ws.tts")


async def _run_stream(svc, req: TtsStreamStart, send: SafeSender, session_id: str) -> None:
    from gateway.app import PROTOCOL_VERSION

    started = time.perf_counter()
    meta = svc.tts.stream_meta(req)
    await send.json({"type": "audio.meta", "session_id": session_id, "protocol": PROTOCOL_VERSION,
                     "sample_rate": meta.sample_rate, "format": "pcm_s16le",
                     "streaming_kind": meta.streaming_kind, "segments": len(meta.segments),
                     "device": meta.device})
    seq = 0
    first_ms = None
    audio_ms = compute_ms = queue_ms = 0.0
    async for chunk in svc.tts.stream(req, session_id):
        if first_ms is None:
            first_ms = (time.perf_counter() - started) * 1000
        await send.json({"type": "segment", "index": chunk.index, "text": chunk.text,
                         "audio_ms": round(chunk.audio_ms, 1), "seq": seq,
                         "timings": chunk.timings.model_dump()})
        await send.bytes(seq.to_bytes(4, "little") + chunk.pcm16)
        seq += 1
        audio_ms += chunk.audio_ms
        compute_ms += chunk.timings.compute_ms
        queue_ms += chunk.timings.queue_wait_ms
    total_ms = (time.perf_counter() - started) * 1000
    await send.json({"type": "done", "session_id": session_id, "metrics": {
        "server_time_to_first_chunk_ms": round(first_ms or 0, 1),
        "server_total_ms": round(total_ms, 1),
        "audio_ms": round(audio_ms, 1),
        "compute_ms_total": round(compute_ms, 1),
        "queue_wait_ms_total": round(queue_ms, 1),
        "rtf": round(compute_ms / audio_ms, 4) if audio_ms else None,
        "segments": seq,
        "device": meta.device,
        "streaming_kind": meta.streaming_kind,
    }})


@router.websocket("/ws/tts")
async def tts_stream(ws: WebSocket) -> None:
    svc = ws.app.state.services
    await ws.accept()
    send = SafeSender(ws)
    session_id = uuid.uuid4().hex[:12]
    task: asyncio.Task | None = None

    async def guarded(req: TtsStreamStart) -> None:
        try:
            await _run_stream(svc, req, send, session_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            err = wrap_exception(exc)
            if not err.is_client_error and not err.logged:
                err.logged = True
                log.error("TTS stream %s failed: %s", session_id, err.message, exc_info=True,
                          extra={"code": err.code.value, "session_id": session_id,
                                 "request_id": session_id, "model_id": req.model_id})
            await send.error(err, session_id)

    try:
        while True:
            text = await ws.receive_text()
            try:
                data = parse_json(text)
                kind = data["type"]
                if kind == "start":
                    if task is not None and not task.done():
                        raise AppError(ErrorCode.INVALID_REQUEST, "A synthesis is already running")
                    try:
                        req = TtsStreamStart.model_validate(data)
                    except ValidationError as exc:
                        raise AppError(ErrorCode.INVALID_REQUEST, "Invalid start message",
                                       {"errors": exc.errors(include_context=False)}) from exc
                    task = asyncio.create_task(guarded(req))
                elif kind == "cancel":
                    if task is not None and not task.done():
                        task.cancel()
                    await send.json({"type": "cancelled", "session_id": session_id})
                elif kind == "ping":
                    await send.json({"type": "pong", "server_time": time.time()})
                else:
                    raise AppError(ErrorCode.INVALID_REQUEST, f"Unknown message type {kind!r}")
            except AppError as exc:
                await send.error(exc, session_id)
    except WebSocketDisconnect:
        pass
    finally:
        if task is not None and not task.done():
            task.cancel()
