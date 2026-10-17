"""Error codes and the application exception shared by all modules."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    MODEL_NOT_DOWNLOADED = "MODEL_NOT_DOWNLOADED"
    MODEL_NOT_LOADED = "MODEL_NOT_LOADED"
    MODEL_BUSY = "MODEL_BUSY"
    MODE_UNSUPPORTED = "MODE_UNSUPPORTED"
    DEVICE_UNAVAILABLE = "DEVICE_UNAVAILABLE"
    ENGINE_UNAVAILABLE = "ENGINE_UNAVAILABLE"
    QUEUE_FULL = "QUEUE_FULL"
    INVALID_AUDIO = "INVALID_AUDIO"
    INVALID_REQUEST = "INVALID_REQUEST"
    INFERENCE_FAILED = "INFERENCE_FAILED"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    OUT_OF_MEMORY = "OUT_OF_MEMORY"
    CANCELLED = "CANCELLED"
    INTERNAL = "INTERNAL"


# HTTP status per code. Codes not listed map to 500.
HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.MODEL_NOT_FOUND: 404,
    ErrorCode.MODEL_NOT_DOWNLOADED: 409,
    ErrorCode.MODEL_NOT_LOADED: 409,
    ErrorCode.MODEL_BUSY: 409,
    ErrorCode.MODE_UNSUPPORTED: 400,
    ErrorCode.DEVICE_UNAVAILABLE: 400,
    ErrorCode.ENGINE_UNAVAILABLE: 400,
    ErrorCode.QUEUE_FULL: 429,
    ErrorCode.INVALID_AUDIO: 400,
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.CANCELLED: 499,
    ErrorCode.OUT_OF_MEMORY: 507,
}

# Errors caused by the caller. They are returned to the caller but are not
# broadcast to the error panel as server errors.
CLIENT_ERRORS = {
    ErrorCode.MODEL_NOT_FOUND,
    ErrorCode.MODEL_NOT_DOWNLOADED,
    ErrorCode.MODEL_NOT_LOADED,
    ErrorCode.MODEL_BUSY,
    ErrorCode.MODE_UNSUPPORTED,
    ErrorCode.DEVICE_UNAVAILABLE,
    ErrorCode.ENGINE_UNAVAILABLE,
    ErrorCode.INVALID_AUDIO,
    ErrorCode.INVALID_REQUEST,
    ErrorCode.CANCELLED,
}


class AppError(Exception):
    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.logged = False  # already reported to the event bus (avoid duplicates)

    @property
    def http_status(self) -> int:
        return HTTP_STATUS.get(self.code, 500)

    @property
    def is_client_error(self) -> bool:
        return self.code in CLIENT_ERRORS

    def to_dict(self, request_id: str | None = None) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
            "request_id": request_id,
        }


def wrap_exception(exc: BaseException, default: ErrorCode = ErrorCode.INFERENCE_FAILED) -> AppError:
    """Convert any exception from an engine into an AppError with a useful code."""
    if isinstance(exc, AppError):
        return exc
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    if isinstance(exc, MemoryError) or "out of memory" in lowered or "e_outofmemory" in lowered:
        return AppError(ErrorCode.OUT_OF_MEMORY, text)
    return AppError(default, text)
