"""Engine adapter contract for STT. Audio is always float32 mono 16 kHz."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np

from common.schemas import Device

SAMPLE_RATE = 16000


@dataclass
class Word:
    text: str
    start_ms: float
    end_ms: float


@dataclass
class Transcript:
    text: str
    language: str | None = None
    segments: list[tuple[str, float, float]] = field(default_factory=list)  # text, start_ms, end_ms
    words: list[Word] | None = None


@dataclass
class TranscribeJob:
    audio: np.ndarray
    language: str | None
    beam_size: int = 1
    word_timestamps: bool = False


@dataclass
class StreamUpdate:
    partial: str | None = None
    finals: list[str] = field(default_factory=list)


class NativeStream(Protocol):
    """Stateful recognizer for one live session (live_native). Not thread-safe:
    the session calls it from one job at a time."""

    def accept(self, audio: np.ndarray) -> StreamUpdate: ...

    def finish(self) -> StreamUpdate: ...


class SttAdapter(Protocol):
    # Longest clip the native batch path accepts (e.g. one Whisper window).
    max_batch_audio_s: float | None

    def load(self, path: Path, device: Device, threads: int) -> str: ...

    def unload(self) -> None: ...

    def transcribe(self, job: TranscribeJob) -> Transcript: ...

    def transcribe_batch(self, jobs: list[TranscribeJob]) -> list[Transcript | BaseException]: ...

    def create_stream(self, language: str | None) -> NativeStream: ...
