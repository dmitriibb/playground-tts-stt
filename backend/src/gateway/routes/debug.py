"""Endpoints that fail on purpose, to check that errors reach the UI error panel."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from common.errors import AppError, ErrorCode

router = APIRouter(prefix="/api/debug", tags=["debug"])
log = logging.getLogger("gateway.debug")


@router.post("/error")
async def raise_error(kind: str = "internal") -> dict:
    if kind == "warning":
        log.warning("Test warning from /api/debug/error", extra={"code": "TEST_WARNING"})
        return {"ok": True}
    if kind == "app":
        raise AppError(ErrorCode.INFERENCE_FAILED, "Test inference failure from /api/debug/error")
    raise RuntimeError("Test crash from /api/debug/error")
