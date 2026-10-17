"""Public TTS DTOs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from common.schemas import ErrorBody, ServerTimings

TtsMode = Literal["tts_file", "tts_stream", "tts_batch"]
StreamingKind = Literal["model_streaming", "segment_streaming", "output_chunked"]


class SynthesizeRequest(BaseModel):
    model_id: str
    text: str = Field(..., min_length=1, max_length=5000)
    voice: str | None = None
    language: str | None = None
    speed: float = Field(1.0, ge=0.5, le=2.0)


class SynthesizeResult(BaseModel):
    model_id: str
    voice: str | None
    sample_rate: int
    audio_wav_b64: str
    audio_duration_ms: float
    segments: int
    timings: ServerTimings


class TtsBatchItem(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    voice: str | None = None
    language: str | None = None
    speed: float = Field(1.0, ge=0.5, le=2.0)


class TtsBatchRequest(BaseModel):
    model_id: str
    items: list[TtsBatchItem] = Field(..., min_length=1, max_length=64)


class TtsBatchItemResult(BaseModel):
    audio_wav_b64: str | None = None
    audio_duration_ms: float | None = None
    error: ErrorBody | None = None


class TtsBatchResult(BaseModel):
    model_id: str
    sample_rate: int
    items: list[TtsBatchItemResult]
    timings: ServerTimings


class TtsStreamStart(BaseModel):
    """`start` message of /ws/tts."""

    type: Literal["start"] = "start"
    model_id: str
    text: str = Field(..., min_length=1, max_length=5000)
    voice: str | None = None
    language: str | None = None
    speed: float = Field(1.0, ge=0.5, le=2.0)
