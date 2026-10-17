from __future__ import annotations

from fastapi import Request, WebSocket

from common.errors import AppError, ErrorCode


def services(request: Request):
    return request.app.state.services


def ws_services(websocket: WebSocket):
    return websocket.app.state.services


def request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def service_for_model(svc, model_id: str):
    """Route a model id to the module that owns it (stt.* / vad.* -> STT, tts.* -> TTS)."""
    for module in (svc.stt, svc.tts):
        if module.has_model(model_id):
            return module
    raise AppError(ErrorCode.MODEL_NOT_FOUND, f"Unknown model {model_id}", {"model_id": model_id})
