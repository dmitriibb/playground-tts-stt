"""Vosk (Kaldi). Native streaming recognizer; CPU only. One model per language."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from common.audio import float_to_pcm16
from common.errors import AppError, ErrorCode
from common.schemas import Device
from stt.adapters.base import SAMPLE_RATE, NativeStream, StreamUpdate, TranscribeJob, Transcript


class _VoskStream:
    def __init__(self, model):
        import vosk

        self._rec = vosk.KaldiRecognizer(model, SAMPLE_RATE)
        self._last_partial = ""

    def accept(self, audio: np.ndarray) -> StreamUpdate:
        update = StreamUpdate()
        if self._rec.AcceptWaveform(float_to_pcm16(audio)):
            text = json.loads(self._rec.Result()).get("text", "")
            if text:
                update.finals.append(text)
            self._last_partial = ""
        else:
            partial = json.loads(self._rec.PartialResult()).get("partial", "")
            if partial != self._last_partial:
                update.partial = partial
                self._last_partial = partial
        return update

    def finish(self) -> StreamUpdate:
        text = json.loads(self._rec.FinalResult()).get("text", "")
        return StreamUpdate(finals=[text] if text else [])


class VoskAdapter:
    max_batch_audio_s: float | None = None

    def __init__(self, language: str):
        self._language = language
        self._model = None

    def load(self, path: Path, device: Device, threads: int) -> str:
        if device != "cpu":
            raise AppError(ErrorCode.DEVICE_UNAVAILABLE, "Vosk runs on CPU only")
        import vosk

        vosk.SetLogLevel(-1)
        self._model = vosk.Model(str(path))
        return "vosk (kaldi) / cpu"

    def unload(self) -> None:
        self._model = None

    def _require(self):
        if self._model is None:
            raise AppError(ErrorCode.MODEL_NOT_LOADED, "Vosk model is not loaded")
        return self._model

    def transcribe(self, job: TranscribeJob) -> Transcript:
        stream = _VoskStream(self._require())
        finals: list[str] = []
        step = SAMPLE_RATE // 2
        for i in range(0, len(job.audio), step):
            finals += stream.accept(job.audio[i:i + step]).finals
        finals += stream.finish().finals
        return Transcript(text=" ".join(finals), language=self._language)

    def transcribe_batch(self, jobs: list[TranscribeJob]) -> list[Transcript | BaseException]:
        raise AppError(ErrorCode.MODE_UNSUPPORTED, "Vosk has no native batching")

    def create_stream(self, language: str | None) -> NativeStream:
        return _VoskStream(self._require())
