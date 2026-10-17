"""Silero VAD v5 (ONNX), used by live_endpointed sessions.

One ONNX session is shared; the recurrent state lives in a per-stream `VadStream`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from common.errors import AppError, ErrorCode
from common.onnx import create_session
from common.schemas import Device

CHUNK = 512  # samples at 16 kHz = 32 ms
CHUNK_MS = 32
_CONTEXT = 64


class SileroVadAdapter:
    max_batch_audio_s: float | None = None

    def __init__(self) -> None:
        self._session = None

    def load(self, path: Path, device: Device, threads: int) -> str:
        self._session, runtime = create_session(path / "silero_vad.onnx", device, threads or 1)
        return runtime

    def unload(self) -> None:
        self._session = None

    def new_stream(self) -> VadStream:
        if self._session is None:
            raise AppError(ErrorCode.MODEL_NOT_LOADED, "Silero VAD is not loaded")
        return VadStream(self._session)


class VadStream:
    def __init__(self, session) -> None:
        self._session = session
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(_CONTEXT, dtype=np.float32)
        self._sr = np.array(16000, dtype=np.int64)

    def prob(self, chunk: np.ndarray) -> float:
        """Speech probability of one 512-sample chunk."""
        x = np.concatenate([self._context, chunk.astype(np.float32, copy=False)])[None, :]
        out, self._state = self._session.run(None, {"input": x, "state": self._state, "sr": self._sr})
        self._context = chunk[-_CONTEXT:]
        return float(out[0][0])

    def probs(self, audio: np.ndarray) -> list[float]:
        return [self.prob(audio[i:i + CHUNK]) for i in range(0, len(audio) - CHUNK + 1, CHUNK)]
