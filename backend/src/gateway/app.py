"""FastAPI app factory: wiring, CORS, request ids and error handling."""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from common.devices import system_info
from common.errors import AppError, ErrorCode
from common.events import EventBus
from common.logging_bridge import setup_logging
from gateway.config import Settings
from stt.service import LocalSttService, SttService
from tts.service import LocalTtsService, TtsService

log = logging.getLogger("gateway.app")

PROTOCOL_VERSION = 0
APP_VERSION = "0.1.0"


@dataclass
class Services:
    settings: Settings
    bus: EventBus
    stt: SttService
    tts: TtsService
    system: dict | None = None


def create_app(
    settings: Settings | None = None,
    stt: SttService | None = None,
    tts: TtsService | None = None,
    bus: EventBus | None = None,
) -> FastAPI:
    settings = settings or Settings()
    bus = bus or EventBus()
    models_dir = settings.models_dir.resolve()
    services = Services(
        settings=settings,
        bus=bus,
        stt=stt or LocalSttService(models_dir / "stt", bus),
        tts=tts or LocalTtsService(models_dir / "tts", bus),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        bus.bind_loop(asyncio.get_running_loop())
        setup_logging(bus, settings.log_level)
        # Hardware probing shells out (GPU names) and may import torch: keep it off the loop.
        services.system = await asyncio.to_thread(system_info)
        log.info("Backend ready. Models dir: %s", models_dir)
        yield
        await services.stt.shutdown()
        await services.tts.shutdown()

    app = FastAPI(title="TTS/STT Playground API", version=APP_VERSION, lifespan=lifespan)
    app.state.services = services

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        rid = getattr(request.state, "request_id", None)
        if not exc.is_client_error and not exc.logged:
            exc.logged = True
            log.error("%s %s failed: %s", request.method, request.url.path, exc.message,
                      extra={"code": exc.code.value, "request_id": rid, "details": exc.details})
        return JSONResponse({"error": exc.to_dict(rid)}, status_code=exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        rid = getattr(request.state, "request_id", None)
        err = AppError(ErrorCode.INVALID_REQUEST, "Invalid request",
                       {"errors": [dict(e, ctx=None) for e in exc.errors()]})
        return JSONResponse({"error": err.to_dict(rid)}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", None)
        log.error("%s %s crashed: %s", request.method, request.url.path, exc, exc_info=exc,
                  extra={"code": ErrorCode.INTERNAL.value, "request_id": rid})
        err = AppError(ErrorCode.INTERNAL, f"{type(exc).__name__}: {exc}")
        return JSONResponse({"error": err.to_dict(rid)}, status_code=500,
                            headers={"Access-Control-Allow-Origin": "*"})

    from gateway.routes import debug, fixtures, health, models, stt_routes, tts_routes
    from gateway.ws import events_ws, stt_ws, tts_ws

    app.include_router(health.router)
    app.include_router(models.router)
    app.include_router(stt_routes.router)
    app.include_router(tts_routes.router)
    app.include_router(fixtures.router)
    if settings.enable_debug_routes:
        app.include_router(debug.router)
    app.include_router(events_ws.router)
    app.include_router(stt_ws.router)
    app.include_router(tts_ws.router)
    return app
