"""Fake engine adapters. They live only in tests and are never exposed by the app."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from common.downloads import DownloadSource
from common.registry import ModelSpec
from common.schemas import RunnerConfig, Voice
from stt.adapters.base import SAMPLE_RATE, StreamUpdate, TranscribeJob, Transcript, Word


class FakeSttAdapter:
    max_batch_audio_s = 30.0

    def __init__(self, delay_s: float = 0.0):
        self.delay_s = delay_s
        self.batches: list[int] = []
        self.loaded = False
        self.concurrent = 0
        self.max_concurrent = 0
        self._lock = threading.Lock()

    def load(self, path: Path, device: str, threads: int) -> str:
        self.loaded = True
        return f"fake / {device}"

    def unload(self) -> None:
        self.loaded = False

    def _enter(self):
        with self._lock:
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)

    def _exit(self):
        with self._lock:
            self.concurrent -= 1

    def transcribe(self, job: TranscribeJob) -> Transcript:
        self._enter()
        try:
            time.sleep(self.delay_s)
            secs = len(job.audio) / SAMPLE_RATE
            words = [Word(f" w{i}", i * 500.0, i * 500.0 + 400) for i in range(int(secs * 2))]
            return Transcript(text=f"audio {secs:.1f}s", language=job.language or "en",
                              segments=[(f"audio {secs:.1f}s", 0.0, secs * 1000)],
                              words=words if job.word_timestamps else None)
        finally:
            self._exit()

    def transcribe_batch(self, jobs: list[TranscribeJob]):
        self.batches.append(len(jobs))
        time.sleep(self.delay_s)
        return [Transcript(text=f"batched {len(j.audio) / SAMPLE_RATE:.1f}s", language="en") for j in jobs]

    def create_stream(self, language):
        return FakeStream()


class FakeStream:
    def __init__(self):
        self.samples = 0

    def accept(self, audio: np.ndarray) -> StreamUpdate:
        self.samples += len(audio)
        if self.samples >= SAMPLE_RATE:  # a "final" every second of audio
            self.samples = 0
            return StreamUpdate(finals=["one second"])
        return StreamUpdate(partial=f"{self.samples} samples")

    def finish(self) -> StreamUpdate:
        return StreamUpdate(finals=["tail"] if self.samples else [])


class FakeTtsAdapter:
    sample_rate = 16000

    def load(self, path: Path, device: str, threads: int) -> str:
        return "fake-tts"

    def unload(self) -> None:
        pass

    def synthesize(self, job) -> np.ndarray:
        if "FAIL" in job.text:
            raise RuntimeError("synthetic engine failure")
        return np.zeros(int(self.sample_rate * 0.1 * len(job.text.split())), dtype=np.float32)

    def synthesize_batch(self, jobs):
        raise NotImplementedError


def stt_spec(adapter: FakeSttAdapter, model_id: str = "stt.fake.model", **kw) -> ModelSpec:
    return ModelSpec(
        id=model_id, task="stt", name="Fake STT", engine="fake", engine_package="numpy",
        engine_module="numpy", adapter_factory=lambda spec: adapter, source=DownloadSource(),
        languages=["en"],
        modes={"file_single": True, "file_batch": True, "live_native": True, "live_windowed": True,
               "live_endpointed": False, "live_batched": False, "file_chunked": False},
        native_batching=kw.pop("native_batching", True),
        default_runner=kw.pop("default_runner", RunnerConfig(max_active=1, max_batch_size=4, max_wait_ms=30)),
        **kw,
    )


def tts_spec(model_id: str = "tts.fake.voice") -> ModelSpec:
    return ModelSpec(
        id=model_id, task="tts", name="Fake TTS", engine="fake", engine_package="numpy",
        engine_module="numpy", adapter_factory=lambda spec: FakeTtsAdapter(), source=DownloadSource(),
        languages=["en"], voices=[Voice(id="v", name="V", language="en")],
        modes={"tts_file": True, "tts_stream": True, "tts_batch": False},
        streaming_kind="segment_streaming",
    )
