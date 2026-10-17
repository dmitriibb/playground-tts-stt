"""Engine adapter contract for TTS. Output audio is float32 mono at `sample_rate`."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from common.schemas import Device


@dataclass
class SynthJob:
    text: str
    voice: str | None
    language: str | None
    speed: float = 1.0


class TtsAdapter(Protocol):
    sample_rate: int

    def load(self, path: Path, device: Device, threads: int) -> str: ...

    def unload(self) -> None: ...

    def synthesize(self, job: SynthJob) -> np.ndarray: ...

    def synthesize_batch(self, jobs: list[SynthJob]) -> list[np.ndarray | BaseException]: ...
