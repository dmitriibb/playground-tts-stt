"""Live STT sessions: one object per /ws/stt connection.

Audio arrives via `feed()` (float32 16 kHz) while a background task processes it,
so receiving frames never waits for inference. Messages go out through `emit`.

- EndpointedSession (live_endpointed): Silero VAD cuts utterances -> offline model
- WindowedSession  (live_windowed):   re-run an offline model on a rolling window,
                                      commit words that left the unstable tail
- NativeSession    (live_native):     stateful streaming recognizer
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from common.errors import AppError, ErrorCode, wrap_exception
from common.runner import JobTimings
from stt.adapters.base import SAMPLE_RATE, NativeStream, StreamUpdate, TranscribeJob, Transcript
from stt.schemas import LiveStartOptions
from stt.vad import CHUNK, CHUNK_MS, VadStream

log = logging.getLogger("stt.sessions")

Emit = Callable[[dict[str, Any]], Awaitable[None]]
TranscribeFn = Callable[[TranscribeJob], Awaitable[tuple[Transcript, JobTimings]]]
StepFn = Callable[[Callable[[Any], Any], Any], Awaitable[tuple[Any, JobTimings]]]


def _ms(samples: int) -> float:
    return samples * 1000 / SAMPLE_RATE


@dataclass
class _Metrics:
    inference_calls: int = 0
    compute_ms: float = 0.0
    queue_wait_ms: float = 0.0
    partials: int = 0
    finals: int = 0
    max_batch_size: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def add(self, t: JobTimings) -> None:
        self.inference_calls += 1
        self.compute_ms += t.compute_ms
        self.queue_wait_ms += t.queue_wait_ms
        self.max_batch_size = max(self.max_batch_size, t.batch_size)


def _timings(t: JobTimings) -> dict[str, Any]:
    return {"queue_wait_ms": round(t.queue_wait_ms, 1), "compute_ms": round(t.compute_ms, 1),
            "batch_id": t.batch_id, "batch_size": t.batch_size}


class LiveSession:
    def __init__(self, session_id: str, opts: LiveStartOptions, emit: Emit, device: str):
        self.session_id = session_id
        self.opts = opts
        self._emit = emit
        self.device = device
        self._pending: list[np.ndarray] = []
        self._received = 0  # samples
        self._new_audio = asyncio.Event()
        self._ended = False
        self._task: asyncio.Task | None = None
        self.metrics = _Metrics()
        self.revision = 0

    # ---- control (called by the gateway) ---------------------------------------------

    def start(self) -> None:
        self._task = asyncio.create_task(self._run_guarded(), name=f"stt-session-{self.session_id}")

    def feed(self, audio: np.ndarray) -> None:
        if self._ended:
            raise AppError(ErrorCode.INVALID_REQUEST, "Audio after end_input")
        self._pending.append(audio)
        self._received += len(audio)
        self._new_audio.set()

    def end_input(self) -> None:
        self._ended = True
        self._new_audio.set()

    async def cancel(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def wait(self) -> None:
        if self._task:
            await asyncio.shield(self._task)

    @property
    def received_ms(self) -> float:
        return _ms(self._received)

    # ---- processing -----------------------------------------------------------------

    async def _next_audio(self) -> np.ndarray | None:
        while True:
            if self._pending:
                audio = np.concatenate(self._pending)
                self._pending.clear()
                return audio
            if self._ended:
                return None
            self._new_audio.clear()
            await self._new_audio.wait()

    async def _run_guarded(self) -> None:
        try:
            await self._run()
            m = self.metrics
            await self._emit({
                "type": "session.completed",
                "session_id": self.session_id,
                "metrics": {
                    "audio_received_ms": round(self.received_ms, 1),
                    "inference_calls": m.inference_calls,
                    "compute_ms_total": round(m.compute_ms, 1),
                    "queue_wait_ms_total": round(m.queue_wait_ms, 1),
                    "partials": m.partials,
                    "finals": m.finals,
                    "max_batch_size": m.max_batch_size,
                    "rtf": round(m.compute_ms / self.received_ms, 3) if self._received else None,
                    "device": self.device,
                    "model_id": self.opts.model_id,
                    "mode": self.opts.mode,
                    **m.extra,
                },
            })
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            err = wrap_exception(exc)
            if not err.is_client_error and not err.logged:
                err.logged = True
                log.error("Live session %s failed: %s", self.session_id, err.message, exc_info=True,
                          extra={"code": err.code.value, "session_id": self.session_id,
                                 "request_id": self.session_id, "model_id": self.opts.model_id})
            await self._emit({"type": "error", "error": err.to_dict(self.session_id)})

    async def _run(self) -> None:
        raise NotImplementedError

    async def _partial(self, text: str, **extra: Any) -> None:
        self.revision += 1
        self.metrics.partials += 1
        await self._emit({"type": "transcript.partial", "text": text, "revision": self.revision,
                          "at_ms": round(self.received_ms, 1), **extra})

    async def _final(self, text: str, start_ms: float, end_ms: float, **extra: Any) -> None:
        self.metrics.finals += 1
        await self._emit({"type": "transcript.final", "text": text, "start_ms": round(start_ms, 1),
                          "end_ms": round(end_ms, 1), "at_ms": round(self.received_ms, 1), **extra})


# ---------------------------------------------------------------------------------------


@dataclass
class _Segment:
    index: int
    audio: np.ndarray
    start_ms: float
    end_ms: float


class EndpointedSession(LiveSession):
    def __init__(self, session_id: str, opts: LiveStartOptions, emit: Emit, device: str,
                 transcribe: TranscribeFn, vad: VadStream):
        super().__init__(session_id, opts, emit, device)
        self._transcribe = transcribe
        self._vad = vad
        v = opts.vad
        self._pre_roll: deque[np.ndarray] = deque(maxlen=max(1, v.pre_roll_ms // CHUNK_MS))
        self._speech: list[np.ndarray] = []
        self._in_speech = False
        self._silence_ms = 0
        self._speech_ms = 0
        self._seg_start = 0  # samples
        self._pos = 0  # samples through VAD
        self._seg_index = 0
        self._segments: asyncio.Queue[_Segment | None] = asyncio.Queue()
        self._events: list[dict[str, Any]] = []
        self._partial_task: asyncio.Task | None = None
        self._last_partial_pos = 0

    async def _run(self) -> None:
        transcriber = asyncio.create_task(self._transcriber())
        try:
            carry = np.zeros(0, dtype=np.float32)
            while (audio := await self._next_audio()) is not None:
                carry = np.concatenate([carry, audio])
                n = len(carry) // CHUNK * CHUNK
                if n == 0:
                    continue
                chunks, carry = carry[:n], carry[n:]
                probs = await asyncio.to_thread(self._vad.probs, chunks)
                for i, p in enumerate(probs):
                    self._step(chunks[i * CHUNK:(i + 1) * CHUNK], p)
                for event in self._events:
                    await self._emit(event)
                self._events.clear()
                self._maybe_partial()
            if self._in_speech:
                self._close_segment()
                for event in self._events:
                    await self._emit(event)
            await self._segments.put(None)
            await transcriber
        finally:
            if not transcriber.done():
                transcriber.cancel()
            if self._partial_task and not self._partial_task.done():
                self._partial_task.cancel()

    def _step(self, chunk: np.ndarray, prob: float) -> None:
        v = self.opts.vad
        if not self._in_speech:
            if prob >= v.threshold:
                self._in_speech = True
                self._speech = list(self._pre_roll)
                self._seg_start = self._pos - sum(len(c) for c in self._pre_roll)
                self._speech.append(chunk)
                self._silence_ms, self._speech_ms = 0, CHUNK_MS
                self._last_partial_pos = self._pos
                self._pre_roll.clear()
                self._events.append({"type": "vad", "state": "speech_start",
                                     "at_ms": round(_ms(self._seg_start), 1)})
            else:
                self._pre_roll.append(chunk)
        else:
            self._speech.append(chunk)
            if prob < max(0.05, v.threshold - 0.15):
                self._silence_ms += CHUNK_MS
            else:
                self._silence_ms = 0
                self._speech_ms += CHUNK_MS
            seg_ms = _ms(sum(len(c) for c in self._speech))
            if self._silence_ms >= v.silence_ms or seg_ms >= v.max_segment_ms:
                self._close_segment()
        self._pos += len(chunk)

    def _close_segment(self) -> None:
        end = self._pos + CHUNK
        self._events.append({"type": "vad", "state": "speech_end", "at_ms": round(_ms(end), 1)})
        if self._speech_ms >= self.opts.vad.min_speech_ms:
            seg = _Segment(self._seg_index, np.concatenate(self._speech), _ms(self._seg_start), _ms(end))
            self._seg_index += 1
            self._segments.put_nowait(seg)
        else:
            self.metrics.extra["dropped_short_segments"] = self.metrics.extra.get(
                "dropped_short_segments", 0) + 1
        self._in_speech = False
        self._speech = []
        self._silence_ms = self._speech_ms = 0

    def _maybe_partial(self) -> None:
        interval = self.opts.vad.partial_interval_ms
        if (not interval or not self._in_speech
                or (self._partial_task and not self._partial_task.done())
                or _ms(self._pos - self._last_partial_pos) < interval):
            return
        self._last_partial_pos = self._pos
        index, audio = self._seg_index, np.concatenate(self._speech)

        async def run() -> None:
            try:
                result, t = await self._transcribe(TranscribeJob(audio, self.opts.language,
                                                                 self.opts.beam_size))
                self.metrics.add(t)
                if index == self._seg_index:  # utterance still open
                    await self._partial(result.text, segment_index=index, timings=_timings(t))
            except AppError as exc:
                if exc.code != ErrorCode.QUEUE_FULL:  # partials are best effort
                    raise

        self._partial_task = asyncio.create_task(run())

    async def _transcriber(self) -> None:
        while (seg := await self._segments.get()) is not None:
            result, t = await self._transcribe(TranscribeJob(seg.audio, self.opts.language,
                                                             self.opts.beam_size))
            self.metrics.add(t)
            await self._final(result.text, seg.start_ms, seg.end_ms, segment_index=seg.index,
                              language=result.language, timings=_timings(t))


class WindowedSession(LiveSession):
    def __init__(self, session_id: str, opts: LiveStartOptions, emit: Emit, device: str,
                 transcribe: TranscribeFn):
        super().__init__(session_id, opts, emit, device)
        self._transcribe = transcribe

    async def _run(self) -> None:
        w = self.opts.window
        stride = w.stride_ms * SAMPLE_RATE // 1000
        size = w.size_ms * SAMPLE_RATE // 1000
        buf = np.zeros(0, dtype=np.float32)
        buf_start = 0  # samples, stream timeline
        since_run = 0
        index = 0
        while (audio := await self._next_audio()) is not None:
            buf = np.concatenate([buf, audio])
            since_run += len(audio)
            if since_run < stride:
                continue
            since_run = 0
            result, t = await self._transcribe(TranscribeJob(
                buf, self.opts.language, self.opts.beam_size, word_timestamps=True))
            self.metrics.add(t)
            words = result.words or []
            if len(buf) < size:
                await self._partial(result.text, timings=_timings(t))
                continue
            # Window full: commit words that ended before the unstable tail.
            cut_ms = _ms(len(buf)) - w.tail_ms
            committed = [x for x in words if x.end_ms <= cut_ms]
            if committed:
                text = "".join(x.text for x in committed).strip()
                cut = int(committed[-1].end_ms * SAMPLE_RATE / 1000)
                rest = "".join(x.text for x in words[len(committed):]).strip()
            else:
                text, cut, rest = result.text, len(buf), ""
            await self._final(text, _ms(buf_start), _ms(buf_start + cut), segment_index=index,
                              timings=_timings(t))
            index += 1
            buf, buf_start = buf[cut:], buf_start + cut
            await self._partial(rest)
        if _ms(len(buf)) >= 300:
            result, t = await self._transcribe(TranscribeJob(buf, self.opts.language, self.opts.beam_size))
            self.metrics.add(t)
            await self._final(result.text, _ms(buf_start), _ms(buf_start + len(buf)),
                              segment_index=index, timings=_timings(t))


class NativeSession(LiveSession):
    def __init__(self, session_id: str, opts: LiveStartOptions, emit: Emit, device: str,
                 stream: NativeStream, step: StepFn):
        super().__init__(session_id, opts, emit, device)
        self._stream = stream
        self._step = step
        self._last_final_ms = 0.0

    async def _publish(self, update: StreamUpdate, t: JobTimings) -> None:
        for text in update.finals:
            await self._final(text, self._last_final_ms, self.received_ms, timings=_timings(t))
            self._last_final_ms = self.received_ms
        if update.partial is not None:
            await self._partial(update.partial, timings=_timings(t))

    async def _run(self) -> None:
        stream = self._stream
        while (audio := await self._next_audio()) is not None:
            update, t = await self._step(stream.accept, audio)
            self.metrics.add(t)
            await self._publish(update, t)
        update, t = await self._step(lambda _: stream.finish(), None)
        self.metrics.add(t)
        await self._publish(update, t)
