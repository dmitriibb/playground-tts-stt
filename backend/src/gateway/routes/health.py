from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from gateway.deps import services

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health(svc=Depends(services)) -> dict:
    from gateway.app import APP_VERSION, PROTOCOL_VERSION

    loaded = [m.id for m in [*svc.stt.list_models(), *svc.tts.list_models()] if m.state.load == "loaded"]
    return {
        "status": "ok",
        "version": APP_VERSION,
        "protocol": PROTOCOL_VERSION,
        "server_time": time.time(),
        "models_dir": str(svc.settings.models_dir.resolve()),
        "loaded_models": loaded,
        "system": svc.system,
    }
