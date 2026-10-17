"""Public facade of the STT module. The gateway imports only this module and `stt.schemas`.

`SttService` is the contract; `LocalSttService` runs models in this process. When STT
becomes its own service, a `RemoteSttService` (HTTP + WS client) implements the same
Protocol and the gateway code stays unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from common.audio import decode_audio, duration_ms, pcm16_to_float
from common.errors import AppError, ErrorCode, wrap_exception
from common.events import EventPublisher
from common.registry import ModelRegistry, ModelSpec
from common.runner import JobTimings, ModelRunner
from common.schemas import (
    ErrorBody,
    LoadRequest,
    ModelInfo,
    RunnerConfigPatch,
    ServerTimings,
)
from stt import catalog as stt_catalog
from stt.adapters.base import SAMPLE_RATE, SttAdapter, TranscribeJob, Transcript
from stt.schemas import (
    BatchItemResult,
    BatchResult,
    LiveStartOptions,
    TranscribeOptions,
    TranscribeResult,
    TranscriptSegment,
)
from stt.sessions import EndpointedSession, LiveSession, NativeSession, WindowedSession
from stt.vad import SileroVadAdapter

Emit = Callable[[dict[str, Any]], Awaitable[None]]


class LiveSessionHandle(Protocol):
    session_id: str
    device: str

    def feed_pcm16(self, data: bytes) -> None: ...

    def end_input(self) -> None: ...

    async def cancel(self) -> None: ...

    async def wait(self) -> None: ...


class SttService(Protocol):
    def list_models(self) -> list[ModelInfo]: ...

    def has_model(self, model_id: str) -> bool: ...

    def model(self, model_id: str) -> ModelInfo: ...

    def start_download(self, model_id: str) -> ModelInfo: ...

    async def delete_files(self, model_id: str) -> ModelInfo: ...

    async def load(self, model_id: str, req: LoadRequest) -> ModelInfo: ...

    async def unload(self, model_id: str) -> ModelInfo: ...

    def patch_runner(self, model_id: str, patch: RunnerConfigPatch) -> ModelInfo: ...

    async def transcribe(self, audio: bytes, opts: TranscribeOptions,
                         request_id: str | None = None) -> TranscribeResult: ...

    async def transcribe_batch(self, files: list[tuple[str, bytes]], opts: TranscribeOptions,
                               request_id: str | None = None) -> BatchResult: ...

    async def open_live_session(self, opts: LiveStartOptions, emit: Emit,
                                session_id: str) -> LiveSessionHandle: ...

    async def shutdown(self) -> None: ...


def _runner_fns(spec: ModelSpec, adapter: Any):
    if spec.task == "vad":
        return (lambda payload: None), None
    return adapter.transcribe, adapter.transcribe_batch


class _Handle:
    def __init__(self, session: LiveSession):
        self._session = session
        self.session_id = session.session_id
        self.device = session.device

    def feed_pcm16(self, data: bytes) -> None:
        self._session.feed(pcm16_to_float(data))

    def end_input(self) -> None:
        self._session.end_input()

    async def cancel(self) -> None:
        await self._session.cancel()

    async def wait(self) -> None:
        await self._session.wait()


class LocalSttService:
    def __init__(self, models_dir: Path, bus: EventPublisher, specs: list[ModelSpec] | None = None):
        self.registry = ModelRegistry(
            "stt", specs if specs is not None else stt_catalog.catalog(), models_dir, bus, _runner_fns
        )

    # ---- model management (delegated to the registry) -------------------------------

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

    def _stt_model(self, model_id: str, mode: str) -> tuple[ModelSpec, SttAdapter, ModelRunner, str]:
        spec, adapter, runner, device = self.registry.loaded(model_id)
        if spec.task != "stt":
            raise AppError(ErrorCode.INVALID_REQUEST, f"{model_id} is not a speech recognition model")
        if not spec.modes.get(mode):
            raise AppError(ErrorCode.MODE_UNSUPPORTED, f"{model_id} does not support {mode}",
                           {"model_id": model_id, "mode": mode, "note": spec.mode_notes.get(mode)})
        return spec, adapter, runner, device

    @staticmethod
    def _batch_key(adapter: SttAdapter, job: TranscribeJob) -> Any:
        """Jobs may share a dynamic batch only if the native batch path accepts them."""
        limit = adapter.max_batch_audio_s
        if limit is None or job.word_timestamps or len(job.audio) > limit * SAMPLE_RATE:
            return None
        return ("batch", job.beam_size)

    def _submitter(self, adapter: SttAdapter, runner: ModelRunner, request_id: str | None):
        async def submit(job: TranscribeJob) -> tuple[Transcript, JobTimings]:
            return await runner.submit(job, batch_key=self._batch_key(adapter, job),
                                       request_id=request_id)
        return submit

    @staticmethod
    def _server_timings(model_id: str, device: str, t: JobTimings, audio_ms: float,
                        batch_size: int | None = None) -> ServerTimings:
        return ServerTimings(
            model_id=model_id, device=device, queue_wait_ms=round(t.queue_wait_ms, 1),
            compute_ms=round(t.compute_ms, 1), batch_id=t.batch_id,
            batch_size=batch_size or t.batch_size, audio_duration_ms=round(audio_ms, 1),
            rtf=round(t.compute_ms / audio_ms, 4) if audio_ms else None,
        )

    async def transcribe(self, audio: bytes, opts: TranscribeOptions,
                         request_id: str | None = None) -> TranscribeResult:
        _, adapter, runner, device = self._stt_model(opts.model_id, "file_single")
        samples = await asyncio.to_thread(decode_audio, audio, SAMPLE_RATE)
        job = TranscribeJob(samples, opts.language, opts.beam_size)
        result, t = await self._submitter(adapter, runner, request_id)(job)
        audio_ms = duration_ms(len(samples), SAMPLE_RATE)
        return TranscribeResult(
            model_id=opts.model_id, text=result.text, language=result.language,
            segments=[TranscriptSegment(text=s, start_ms=a, end_ms=b) for s, a, b in result.segments],
            timings=self._server_timings(opts.model_id, device, t, audio_ms),
        )

    async def transcribe_batch(self, files: list[tuple[str, bytes]], opts: TranscribeOptions,
                               request_id: str | None = None) -> BatchResult:
        """file_batch: one explicit batch from one client, computed in one native call."""
        _, adapter, runner, device = self._stt_model(opts.model_id, "file_batch")
        if not files:
            raise AppError(ErrorCode.INVALID_REQUEST, "No files in batch")
        decoded: list[tuple[str, np.ndarray | AppError]] = []
        for name, data in files:
            try:
                decoded.append((name, await asyncio.to_thread(decode_audio, data, SAMPLE_RATE)))
            except AppError as exc:
                decoded.append((name, exc))
        limit = adapter.max_batch_audio_s
        jobs, slots = [], []
        items: list[BatchItemResult] = []
        for name, audio in decoded:
            if isinstance(audio, AppError):
                items.append(BatchItemResult(filename=name, error=ErrorBody(**audio.to_dict(request_id))))
                continue
            dur = duration_ms(len(audio), SAMPLE_RATE)
            if limit is not None and dur > limit * 1000:
                err = AppError(ErrorCode.INVALID_AUDIO,
                               f"{name} is {dur / 1000:.1f} s; file_batch accepts clips up to {limit:.0f} s")
                items.append(BatchItemResult(filename=name, audio_duration_ms=dur,
                                             error=ErrorBody(**err.to_dict(request_id))))
                continue
            items.append(BatchItemResult(filename=name, audio_duration_ms=dur))
            slots.append(len(items) - 1)
            jobs.append(TranscribeJob(audio, opts.language, opts.beam_size))
        if not jobs:
            raise AppError(ErrorCode.INVALID_AUDIO, "No usable files in batch",
                           {"items": [i.model_dump() for i in items]})
        results, t = await runner.submit(jobs, fn=adapter.transcribe_batch, request_id=request_id)
        for slot, res in zip(slots, results, strict=True):
            if isinstance(res, BaseException):
                err = wrap_exception(res)
                items[slot].error = ErrorBody(**err.to_dict(request_id))
            else:
                items[slot].text, items[slot].language = res.text, res.language
        total_audio = sum(len(j.audio) for j in jobs) * 1000 / SAMPLE_RATE
        return BatchResult(model_id=opts.model_id, items=items,
                           timings=self._server_timings(opts.model_id, device, t, total_audio,
                                                        batch_size=len(jobs)))

    async def open_live_session(self, opts: LiveStartOptions, emit: Emit,
                                session_id: str) -> LiveSessionHandle:
        _, adapter, runner, device = self._stt_model(opts.model_id, opts.mode)
        session: LiveSession
        if opts.mode == "live_native":
            stream = adapter.create_stream(opts.language)

            async def step(fn, payload):
                return await runner.submit(payload, fn=fn, request_id=session_id)

            session = NativeSession(session_id, opts, emit, device, stream, step)
        elif opts.mode == "live_windowed":
            session = WindowedSession(session_id, opts, emit, device,
                                      self._submitter(adapter, runner, session_id))
        elif opts.mode == "live_endpointed":
            vad_id = opts.vad.model_id
            try:
                _, vad_adapter, _, _ = self.registry.loaded(vad_id)
            except AppError as exc:
                raise AppError(ErrorCode.MODEL_NOT_LOADED,
                               f"live_endpointed needs the VAD model: load {vad_id} in Management",
                               {"model_id": vad_id}) from exc
            assert isinstance(vad_adapter, SileroVadAdapter)
            session = EndpointedSession(session_id, opts, emit, device,
                                        self._submitter(adapter, runner, session_id),
                                        vad_adapter.new_stream())
        else:
            raise AppError(ErrorCode.MODE_UNSUPPORTED, f"Unknown live mode {opts.mode}")
        session.start()
        return _Handle(session)
