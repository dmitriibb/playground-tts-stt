"""Base DTOs shared by the STT and TTS modules and the gateway."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Device = Literal["cpu", "gpu"]
DownloadState = Literal["not_downloaded", "downloading", "downloaded", "error"]
LoadState = Literal["unloaded", "loading", "loaded", "unloading", "error"]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class Voice(BaseModel):
    id: str
    name: str
    language: str
    gender: str | None = None


class RunnerConfig(BaseModel):
    """Scheduling knobs of one loaded model."""

    max_active: int = Field(1, ge=1, le=32, description="Requests computed in parallel (worker threads)")
    max_queued: int = Field(32, ge=0, le=1000, description="Waiting requests before QUEUE_FULL")
    max_batch_size: int = Field(1, ge=1, le=64, description="Dynamic batch size (native batching only)")
    max_wait_ms: int = Field(0, ge=0, le=5000, description="How long to wait to fill a batch")


class RunnerConfigPatch(BaseModel):
    max_active: int | None = Field(None, ge=1, le=32)
    max_queued: int | None = Field(None, ge=0, le=1000)
    max_batch_size: int | None = Field(None, ge=1, le=64)
    max_wait_ms: int | None = Field(None, ge=0, le=5000)


class RunnerState(RunnerConfig):
    active: int = 0
    queued: int = 0
    completed: int = 0
    failed: int = 0
    rejected: int = 0
    batches: int = 0


class ModelState(BaseModel):
    download: DownloadState = "not_downloaded"
    download_progress: float = 0.0
    downloaded_mb: float | None = None
    path: str
    load: LoadState = "unloaded"
    device: Device | None = None
    runtime: str | None = None
    threads: int | None = None
    ram_mb: float | None = None
    vram_mb: float | None = None
    load_time_ms: float | None = None
    runner: RunnerState | None = None
    error: str | None = None


class ModelInfo(BaseModel):
    id: str
    task: Literal["stt", "tts", "vad"]
    name: str
    engine: str
    engine_version: str | None = None
    source: str
    params: str | None = None
    disk_size_mb: float | None = None
    est_ram_mb: float | None = None
    est_vram_mb: float | None = None
    languages: list[str]
    voices: list[Voice] | None = None
    devices_supported: list[Device]
    devices_available_now: list[Device]
    device_unavailable_reason: str | None = None
    modes: dict[str, bool]
    mode_notes: dict[str, str] = Field(default_factory=dict)
    streaming_kind: str | None = None
    native_batching: bool = False
    license: str | None = None
    license_note: str | None = None
    notes: str | None = None
    engine_available: bool = True
    unavailable_reason: str | None = None
    state: ModelState


class LoadRequest(BaseModel):
    device: Device = "cpu"
    threads: int = Field(0, ge=0, le=128, description="Intra-op threads per request (0 = engine default)")
    runner: RunnerConfig | None = None


class RunnerPatchResponse(BaseModel):
    model: ModelInfo
    applied: Literal["live"] = "live"


class ServerTimings(BaseModel):
    """Measured on the server for one inference request."""

    model_id: str
    device: str | None = None
    queue_wait_ms: float
    compute_ms: float
    batch_id: int
    batch_size: int
    audio_duration_ms: float | None = None
    rtf: float | None = None
