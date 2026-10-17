"""Public facade of the TTS module. The gateway imports only this module and `tts.schemas`."""

from __future__ import annotations

import base64
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from common.audio import duration_ms, encode_wav, float_to_pcm16
from common.errors import AppError, ErrorCode, wrap_exception
from common.events import EventPublisher
from common.registry import ModelRegistry, ModelSpec
from common.runner import JobTimings
from common.schemas import ErrorBody, LoadRequest, ModelInfo, RunnerConfigPatch, ServerTimings
from tts import catalog as tts_catalog
from tts.adapters.base import SynthJob, TtsAdapter
from tts.schemas import (
    SynthesizeRequest,
    SynthesizeResult,
    TtsBatchItemResult,
    TtsBatchRequest,
    TtsBatchResult,
    TtsStreamStart,
)


@dataclass
class StreamMeta:
    sample_rate: int
    streaming_kind: str
    segments: list[str]
    device: str


@dataclass
class StreamChunk:
    index: int
    text: str
    pcm16: bytes
    audio_ms: float
    timings: ServerTimings


class TtsService(Protocol):
    def list_models(self) -> list[ModelInfo]: ...

    def has_model(self, model_id: str) -> bool: ...

    def model(self, model_id: str) -> ModelInfo: ...

    def start_download(self, model_id: str) -> ModelInfo: ...

    async def delete_files(self, model_id: str) -> ModelInfo: ...

    async def load(self, model_id: str, req: LoadRequest) -> ModelInfo: ...

    async def unload(self, model_id: str) -> ModelInfo: ...

    def patch_runner(self, model_id: str, patch: RunnerConfigPatch) -> ModelInfo: ...

    async def synthesize(self, req: SynthesizeRequest, request_id: str | None = None) -> SynthesizeResult: ...

    async def synthesize_batch(self, req: TtsBatchRequest, request_id: str | None = None) -> TtsBatchResult: ...

    def stream_meta(self, req: TtsStreamStart) -> StreamMeta: ...

    def stream(self, req: TtsStreamStart, request_id: str | None = None) -> AsyncIterator[StreamChunk]: ...

    async def shutdown(self) -> None: ...


_SENTENCE_END = re.compile(r"(?<=[.!?…;])\s+|\n+")


def split_segments(text: str, min_chars: int = 20) -> list[str]:
    """Split text into sentences; glue very short pieces to the next one."""
    parts = [p.strip() for p in _SENTENCE_END.split(text) if p and p.strip()]
    out: list[str] = []
    buf = ""
    for part in parts:
        buf = f"{buf} {part}".strip() if buf else part
        if len(buf) >= min_chars:
            out.append(buf)
            buf = ""
    if buf:
        if out and len(buf) < min_chars:
            out[-1] = f"{out[-1]} {buf}"
        else:
            out.append(buf)
    return out


def _runner_fns(spec: ModelSpec, adapter: Any):
    return adapter.synthesize, adapter.synthesize_batch


class LocalTtsService:
    def __init__(self, models_dir: Path, bus: EventPublisher, specs: list[ModelSpec] | None = None):
        self.registry = ModelRegistry(
            "tts", specs if specs is not None else tts_catalog.catalog(), models_dir, bus, _runner_fns
        )

    def list_models(self) -> list[ModelInfo]:
        return self.registry.list_models()

    def has_model(self, model_id: str) -> bool:
        return self.registry.has(model_id)

    def model(self, model_id: str) -> ModelInfo:
        return self.registry.info(model_id)

    def start_download(self, model_id: str) -> ModelInfo:
        return self.registry.start_download(model_id)

    async def delete_files(self, model_id: str) -> ModelInfo:
        return await self.registry.delete_files(model_id)

    async def load(self, model_id: str, req: LoadRequest) -> ModelInfo:
        return await self.registry.load(model_id, req)

    async def unload(self, model_id: str) -> ModelInfo:
        return await self.registry.unload(model_id)

    def patch_runner(self, model_id: str, patch: RunnerConfigPatch) -> ModelInfo:
        return self.registry.patch_runner(model_id, patch)

    async def shutdown(self) -> None:
        await self.registry.shutdown()

    # ---- inference ------------------------------------------------------------------

    def _tts_model(self, model_id: str, mode: str):
        spec, adapter, runner, device = self.registry.loaded(model_id)
        if not spec.modes.get(mode):
            raise AppError(ErrorCode.MODE_UNSUPPORTED, f"{model_id} does not support {mode}",
                           {"model_id": model_id, "mode": mode, "note": spec.mode_notes.get(mode)})
        return spec, adapter, runner, device

    @staticmethod
    def _timings(model_id: str, device: str, t: JobTimings, audio_ms: float,
                 compute_ms: float | None = None, queue_ms: float | None = None,
                 batch_size: int | None = None) -> ServerTimings:
        compute = t.compute_ms if compute_ms is None else compute_ms
        return ServerTimings(
            model_id=model_id, device=device,
            queue_wait_ms=round(t.queue_wait_ms if queue_ms is None else queue_ms, 1),
            compute_ms=round(compute, 1), batch_id=t.batch_id, batch_size=batch_size or t.batch_size,
            audio_duration_ms=round(audio_ms, 1), rtf=round(compute / audio_ms, 4) if audio_ms else None,
        )

    async def synthesize(self, req: SynthesizeRequest, request_id: str | None = None) -> SynthesizeResult:
        _, adapter, runner, device = self._tts_model(req.model_id, "tts_file")
        adapter: TtsAdapter
        job = SynthJob(req.text, req.voice, req.language, req.speed)
        audio, t = await runner.submit(job, request_id=request_id)
        audio_ms = duration_ms(len(audio), adapter.sample_rate)
        return SynthesizeResult(
            model_id=req.model_id, voice=req.voice, sample_rate=adapter.sample_rate,
            audio_wav_b64=base64.b64encode(encode_wav(audio, adapter.sample_rate)).decode(),
            audio_duration_ms=round(audio_ms, 1), segments=1,
            timings=self._timings(req.model_id, device, t, audio_ms),
        )

    async def synthesize_batch(self, req: TtsBatchRequest, request_id: str | None = None) -> TtsBatchResult:
        _, adapter, runner, device = self._tts_model(req.model_id, "tts_batch")
        jobs = [SynthJob(i.text, i.voice, i.language, i.speed) for i in req.items]
        results, t = await runner.submit(jobs, fn=adapter.synthesize_batch, request_id=request_id)
        items, total_ms = [], 0.0
        for res in results:
            if isinstance(res, BaseException):
                items.append(TtsBatchItemResult(error=ErrorBody(**wrap_exception(res).to_dict(request_id))))
                continue
            ms = duration_ms(len(res), adapter.sample_rate)
            total_ms += ms
            items.append(TtsBatchItemResult(
                audio_wav_b64=base64.b64encode(encode_wav(res, adapter.sample_rate)).decode(),
                audio_duration_ms=round(ms, 1)))
        return TtsBatchResult(model_id=req.model_id, sample_rate=adapter.sample_rate, items=items,
                              timings=self._timings(req.model_id, device, t, total_ms,
                                                    batch_size=len(jobs)))

    def stream_meta(self, req: TtsStreamStart) -> StreamMeta:
        spec, adapter, _, device = self._tts_model(req.model_id, "tts_stream")
        segments = split_segments(req.text)
        if not segments:
            raise AppError(ErrorCode.INVALID_REQUEST, "Nothing to synthesize")
        return StreamMeta(sample_rate=adapter.sample_rate,
                          streaming_kind=spec.streaming_kind or "segment_streaming",
                          segments=segments, device=device)

    async def stream(self, req: TtsStreamStart, request_id: str | None = None) -> AsyncIterator[StreamChunk]:
        """segment_streaming: synthesize sentence by sentence, yield each as soon as it is ready."""
        _, adapter, runner, device = self._tts_model(req.model_id, "tts_stream")
        for index, text in enumerate(split_segments(req.text)):
            audio, t = await runner.submit(SynthJob(text, req.voice, req.language, req.speed),
                                           request_id=request_id)
            audio = np.asarray(audio, dtype=np.float32)
            audio_ms = duration_ms(len(audio), adapter.sample_rate)
            yield StreamChunk(index=index, text=text, pcm16=float_to_pcm16(audio), audio_ms=audio_ms,
                              timings=self._timings(req.model_id, device, t, audio_ms))
