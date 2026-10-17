"""Public STT DTOs (used by the gateway and, after the split, by the HTTP contract)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from common.schemas import ErrorBody, ServerTimings

SttMode = Literal[
    "file_single", "file_batch", "file_chunked",
    "live_native", "live_windowed", "live_endpointed", "live_batched",
]
LiveMode = Literal["live_native", "live_windowed", "live_endpointed"]

STT_MODES: tuple[str, ...] = (
    "file_single", "file_batch", "live_native", "live_windowed", "live_endpointed",
    "live_batched", "file_chunked",
)


class TranscriptSegment(BaseModel):
    text: str
    start_ms: float
    end_ms: float


class TranscribeOptions(BaseModel):
    model_id: str
    language: str | None = Field(None, description="ISO code (en, ru, de); None = auto-detect")
    beam_size: int = Field(1, ge=1, le=10)


class TranscribeResult(BaseModel):
    model_id: str
    text: str
    language: str | None = None
    segments: list[TranscriptSegment] = []
    timings: ServerTimings


class BatchItemResult(BaseModel):
    filename: str
    text: str | None = None
    language: str | None = None
    error: ErrorBody | None = None
    audio_duration_ms: float | None = None


class BatchResult(BaseModel):
    model_id: str
    items: list[BatchItemResult]
    timings: ServerTimings


class VadOptions(BaseModel):
    model_id: str = "vad.silero.v5"
    threshold: float = Field(0.5, ge=0.05, le=0.95)
    silence_ms: int = Field(700, ge=100, le=5000, description="Silence that ends an utterance")
    pre_roll_ms: int = Field(300, ge=0, le=2000, description="Audio kept before speech start")
    min_speech_ms: int = Field(250, ge=0, le=5000, description="Shorter utterances are dropped")
    max_segment_ms: int = Field(15000, ge=1000, le=30000, description="Force a cut after this long")
    partial_interval_ms: int = Field(0, ge=0, le=10000,
                                     description="Re-transcribe the open utterance for partials (0 = off)")


class WindowOptions(BaseModel):
    size_ms: int = Field(6000, ge=1000, le=30000, description="Max audio held before committing")
    stride_ms: int = Field(1000, ge=200, le=10000, description="Re-run the model after this much new audio")
    tail_ms: int = Field(1500, ge=0, le=10000, description="Recent audio never committed (may change)")


class LiveStartOptions(BaseModel):
    """`start` message of /ws/stt."""

    type: Literal["start"] = "start"
    model_id: str
    mode: LiveMode
    language: str | None = None
    sample_rate: Literal[16000] = 16000
    format: Literal["pcm_s16le"] = "pcm_s16le"
    frame_ms: int = Field(40, ge=10, le=1000)
    beam_size: int = Field(1, ge=1, le=10)
    vad: VadOptions = VadOptions()
    window: WindowOptions = WindowOptions()
