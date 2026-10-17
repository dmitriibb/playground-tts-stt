"""faster-whisper (CTranslate2). CPU only on AMD: CTranslate2 GPU support is CUDA-only.

Native batching: clips up to 30 s (one Whisper window) are batched in a single
encoder/decoder call (`transcribe_batch`). Longer clips go through `transcribe`.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from common.errors import AppError, ErrorCode
from common.schemas import Device
from stt.adapters.base import SAMPLE_RATE, NativeStream, TranscribeJob, Transcript, Word


class FasterWhisperAdapter:
    max_batch_audio_s: float | None = 30.0

    def __init__(self, num_workers: int = 4):
        self._model = None
        self._num_workers = num_workers
        self._tokenizers: dict[str | None, object] = {}
        self._tok_lock = threading.Lock()

    def load(self, path: Path, device: Device, threads: int) -> str:
        if device != "cpu":
            raise AppError(ErrorCode.DEVICE_UNAVAILABLE,
                           "faster-whisper (CTranslate2) supports only CPU on AMD GPUs")
        import ctranslate2
        from faster_whisper import WhisperModel

        # num_workers > 1 lets concurrent requests (max_active > 1) run in parallel.
        self._model = WhisperModel(str(path), device="cpu", compute_type="int8",
                                   cpu_threads=threads, num_workers=self._num_workers)
        return (f"ctranslate2 {ctranslate2.__version__} / int8 / "
                f"{threads or 'default'} threads x {self._num_workers} workers")

    def unload(self) -> None:
        self._model = None
        self._tokenizers.clear()

    @property
    def model(self):
        if self._model is None:
            raise AppError(ErrorCode.MODEL_NOT_LOADED, "faster-whisper model is not loaded")
        return self._model

    def transcribe(self, job: TranscribeJob) -> Transcript:
        segments, info = self.model.transcribe(
            job.audio, language=job.language, beam_size=job.beam_size,
            word_timestamps=job.word_timestamps, vad_filter=False,
            condition_on_previous_text=False,
        )
        texts, segs, words = [], [], []
        for seg in segments:
            texts.append(seg.text.strip())
            segs.append((seg.text.strip(), seg.start * 1000, seg.end * 1000))
            for w in seg.words or []:
                words.append(Word(w.word, w.start * 1000, w.end * 1000))
        return Transcript(text=" ".join(t for t in texts if t), language=info.language,
                          segments=segs, words=words if job.word_timestamps else None)

    # ---- native batching -------------------------------------------------------------

    def _tokenizer(self, language: str | None):
        from faster_whisper.tokenizer import Tokenizer

        with self._tok_lock:
            tok = self._tokenizers.get(language)
            if tok is None:
                m = self.model
                tok = Tokenizer(m.hf_tokenizer, m.model.is_multilingual, task="transcribe",
                                language=language or "en")
                self._tokenizers[language] = tok
            return tok

    def transcribe_batch(self, jobs: list[TranscribeJob]) -> list[Transcript | BaseException]:
        from faster_whisper.audio import pad_or_trim
        from faster_whisper.transcribe import get_suppressed_tokens

        m = self.model
        for job in jobs:
            if len(job.audio) > SAMPLE_RATE * 30:
                raise AppError(ErrorCode.INVALID_REQUEST, "Batched clips must be at most 30 s long")
        features = np.stack([pad_or_trim(m.feature_extractor(j.audio)[..., :-1]) for j in jobs])
        encoder_output = m.encode(features)

        languages: list[str] = []
        detected = None
        for i, job in enumerate(jobs):
            if job.language:
                languages.append(job.language)
            elif not m.model.is_multilingual:
                languages.append("en")
            else:
                if detected is None:
                    detected = m.model.detect_language(encoder_output)
                languages.append(detected[i][0][0][2:-2])  # "<|en|>" -> "en"

        prompts = []
        for lang in languages:
            tok = self._tokenizer(lang)
            prompts.append(m.get_prompt(tok, previous_tokens=[], without_timestamps=True))
        tok0 = self._tokenizer(languages[0])
        results = m.model.generate(
            encoder_output, prompts,
            beam_size=max(j.beam_size for j in jobs),
            max_length=m.max_length,
            suppress_blank=True,
            suppress_tokens=get_suppressed_tokens(tok0, [-1]),
            return_no_speech_prob=True,
        )
        out: list[Transcript | BaseException] = []
        for job, lang, res in zip(jobs, languages, results, strict=True):
            text = self._tokenizer(lang).decode(res.sequences_ids[0]).strip()
            dur = len(job.audio) * 1000 / SAMPLE_RATE
            out.append(Transcript(text=text, language=lang, segments=[(text, 0.0, dur)] if text else []))
        return out

    def create_stream(self, language: str | None) -> NativeStream:
        raise AppError(ErrorCode.MODE_UNSUPPORTED, "faster-whisper has no native streaming")
