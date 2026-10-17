from __future__ import annotations

from fastapi import APIRouter, Depends

from gateway.deps import request_id, services
from tts.schemas import SynthesizeRequest, SynthesizeResult, TtsBatchRequest, TtsBatchResult

router = APIRouter(prefix="/api/tts", tags=["tts"])


@router.post("/synthesize", response_model=SynthesizeResult)
async def synthesize(req: SynthesizeRequest, svc=Depends(services),
                     rid: str | None = Depends(request_id)) -> SynthesizeResult:
    """tts_file: whole text -> one WAV (base64) + server timings."""
    return await svc.tts.synthesize(req, rid)


@router.post("/batch", response_model=TtsBatchResult)
async def batch(req: TtsBatchRequest, svc=Depends(services),
                rid: str | None = Depends(request_id)) -> TtsBatchResult:
    """tts_batch: only for engines with native batching (MODE_UNSUPPORTED otherwise)."""
    return await svc.tts.synthesize_batch(req, rid)
