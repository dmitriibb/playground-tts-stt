from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import ValidationError

from common.errors import AppError, ErrorCode
from gateway.deps import request_id, services
from stt.schemas import BatchResult, TranscribeOptions, TranscribeResult

router = APIRouter(prefix="/api/stt", tags=["stt"])


def _options(raw: str) -> TranscribeOptions:
    try:
        return TranscribeOptions.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise AppError(ErrorCode.INVALID_REQUEST, f"Bad options JSON: {exc}") from exc


@router.post("/transcribe", response_model=TranscribeResult)
async def transcribe(
    file: UploadFile = File(...),
    options: str = Form(..., description='JSON: {"model_id": ..., "language": "en"}'),
    svc=Depends(services),
    rid: str | None = Depends(request_id),
) -> TranscribeResult:
    """file_single: one file, one transcript."""
    return await svc.stt.transcribe(await file.read(), _options(options), rid)


@router.post("/batch", response_model=BatchResult)
async def batch(
    files: list[UploadFile] = File(...),
    options: str = Form(...),
    svc=Depends(services),
    rid: str | None = Depends(request_id),
) -> BatchResult:
    """file_batch: N files from one client computed as one native batch."""
    payload = [(f.filename or f"file{i}", await f.read()) for i, f in enumerate(files)]
    return await svc.stt.transcribe_batch(payload, _options(options), rid)
