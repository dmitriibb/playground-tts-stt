"""Piper (VITS, ONNX). One voice per model file. CPU, or GPU through the ONNX Runtime
GPU provider (DirectML on Windows)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from common.errors import AppError, ErrorCode
from common.onnx import create_session
from common.schemas import Device
from tts.adapters.base import SynthJob


class PiperAdapter:
    def __init__(self) -> None:
        self._voice = None
        self.sample_rate = 22050

    def load(self, path: Path, device: Device, threads: int) -> str:
        from piper import PiperConfig, PiperVoice
        from piper.phonemize_espeak import ESPEAK_DATA_DIR

        onnx_files = sorted(path.rglob("*.onnx"))
        if not onnx_files:
            raise AppError(ErrorCode.MODEL_NOT_DOWNLOADED, f"No .onnx voice in {path}")
        model = onnx_files[0]
        config = json.loads(Path(f"{model}.json").read_text(encoding="utf-8"))
        session, runtime = create_session(model, device, threads)
        self._voice = PiperVoice(
            config=PiperConfig.from_dict(config), session=session,
            espeak_data_dir=Path(ESPEAK_DATA_DIR), download_dir=path,
        )
        self.sample_rate = self._voice.config.sample_rate
        return runtime

    def unload(self) -> None:
        self._voice = None

    def synthesize(self, job: SynthJob) -> np.ndarray:
        from piper import SynthesisConfig

        if self._voice is None:
            raise AppError(ErrorCode.MODEL_NOT_LOADED, "Piper voice is not loaded")
        cfg = SynthesisConfig(length_scale=1.0 / job.speed)
        chunks = [c.audio_float_array for c in self._voice.synthesize(job.text, cfg)]
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32, copy=False)

    def synthesize_batch(self, jobs: list[SynthJob]) -> list[np.ndarray | BaseException]:
        raise AppError(ErrorCode.MODE_UNSUPPORTED, "Piper has no native batching")
