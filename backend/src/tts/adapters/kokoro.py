"""Kokoro 82M via kokoro-onnx. CPU, or GPU through the ONNX Runtime GPU provider."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from common.errors import AppError, ErrorCode
from common.onnx import create_session
from common.schemas import Device
from tts.adapters.base import SynthJob

# Kokoro voice prefix -> espeak language
_LANG_BY_PREFIX = {"a": "en-us", "b": "en-gb"}


class KokoroAdapter:
    sample_rate = 24000

    def __init__(self, model_file: str, default_voice: str = "af_heart"):
        self._model_file = model_file
        self._default_voice = default_voice
        self._kokoro = None

    def load(self, path: Path, device: Device, threads: int) -> str:
        from kokoro_onnx import Kokoro

        session, runtime = create_session(path / self._model_file, device, threads)
        self._kokoro = Kokoro.from_session(session, str(path / "voices-v1.0.bin"))
        return runtime

    def unload(self) -> None:
        self._kokoro = None

    def synthesize(self, job: SynthJob) -> np.ndarray:
        if self._kokoro is None:
            raise AppError(ErrorCode.MODEL_NOT_LOADED, "Kokoro is not loaded")
        voice = job.voice or self._default_voice
        if voice not in self._kokoro.voices:
            raise AppError(ErrorCode.INVALID_REQUEST, f"Unknown Kokoro voice {voice}")
        lang = _LANG_BY_PREFIX.get(voice[0], "en-us")
        audio, _ = self._kokoro.create(job.text, voice=voice, speed=job.speed, lang=lang)
        return np.asarray(audio, dtype=np.float32)

    def synthesize_batch(self, jobs: list[SynthJob]) -> list[np.ndarray | BaseException]:
        raise AppError(ErrorCode.MODE_UNSUPPORTED, "kokoro-onnx has no native batching")
