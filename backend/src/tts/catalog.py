"""Known TTS models."""

from __future__ import annotations

from common.downloads import DownloadSource, HfFiles, UrlFile
from common.onnx import ort_devices
from common.registry import ModelSpec
from common.schemas import RunnerConfig, Voice
from tts.adapters.kokoro import KokoroAdapter
from tts.adapters.piper import PiperAdapter

_TTS_MODES = {"tts_file": True, "tts_stream": True, "tts_batch": False}
_SEGMENT_NOTES = {
    "tts_stream": "segment_streaming: text is split into sentences, each synthesized fully and sent",
    "tts_batch": "No native batching in this engine",
}

_KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
_KOKORO_VOICES = [
    ("af_heart", "Heart", "en-us", "female"), ("af_bella", "Bella", "en-us", "female"),
    ("af_nicole", "Nicole", "en-us", "female"), ("af_sarah", "Sarah", "en-us", "female"),
    ("af_sky", "Sky", "en-us", "female"), ("am_adam", "Adam", "en-us", "male"),
    ("am_michael", "Michael", "en-us", "male"), ("am_eric", "Eric", "en-us", "male"),
    ("bf_emma", "Emma", "en-gb", "female"), ("bf_isabella", "Isabella", "en-gb", "female"),
    ("bm_george", "George", "en-gb", "male"), ("bm_lewis", "Lewis", "en-gb", "male"),
]


def _piper(lang: str, locale: str, speaker: str, quality: str, gender: str) -> ModelSpec:
    name = f"{locale}-{speaker}-{quality}"
    base = f"{lang}/{locale}/{speaker}/{quality}/{name}"
    return ModelSpec(
        id=f"tts.piper.{name}",
        task="tts",
        name=f"Piper {locale} {speaker} ({quality})",
        engine="piper",
        engine_package="piper-tts",
        engine_module="piper",
        adapter_factory=lambda spec: PiperAdapter(),
        source=DownloadSource(hf=HfFiles(repo="rhasspy/piper-voices", revision="v1.0.0",
                                         patterns=[f"{base}.onnx", f"{base}.onnx.json"])),
        languages=[lang],
        voices=[Voice(id=speaker, name=speaker.capitalize(), language=locale, gender=gender)],
        modes=_TTS_MODES,
        mode_notes=_SEGMENT_NOTES,
        params="~15M (VITS)",
        disk_size_mb=63,
        est_ram_mb=150,
        devices_supported=["cpu", "gpu"],
        devices_now=ort_devices,
        streaming_kind="segment_streaming",
        default_runner=RunnerConfig(max_active=2, max_queued=32),
        license="Voice: see model card; piper1 code: GPL-3.0",
        license_note="piper-tts (piper1) is GPL-3.0. Fine for a personal playground.",
        notes="Fast CPU baseline. One voice per model file.",
    )


def _kokoro(variant: str, model_file: str, disk_mb: float, ram_mb: float, notes: str,
            gpu: bool) -> ModelSpec:
    return ModelSpec(
        id=f"tts.kokoro.v1-{variant}",
        task="tts",
        name=f"Kokoro 82M v1.0 ({variant})",
        engine="kokoro-onnx",
        engine_package="kokoro-onnx",
        engine_module="kokoro_onnx",
        adapter_factory=lambda spec: KokoroAdapter(model_file),
        source=DownloadSource(urls=[
            UrlFile(url=f"{_KOKORO_RELEASE}/{model_file}", filename=model_file),
            UrlFile(url=f"{_KOKORO_RELEASE}/voices-v1.0.bin", filename="voices-v1.0.bin"),
        ]),
        languages=["en"],
        voices=[Voice(id=v, name=n, language=lang, gender=g) for v, n, lang, g in _KOKORO_VOICES],
        modes=_TTS_MODES,
        mode_notes=_SEGMENT_NOTES,
        params="82M",
        disk_size_mb=disk_mb,
        est_ram_mb=ram_mb,
        devices_supported=["cpu", "gpu"] if gpu else ["cpu"],
        devices_now=ort_devices,
        streaming_kind="segment_streaming",
        default_runner=RunnerConfig(max_active=1, max_queued=32),
        license="Apache-2.0",
        notes=notes + " English only among EN/RU/DE.",
    )


def catalog() -> list[ModelSpec]:
    return [
        _piper("en", "en_US", "lessac", "medium", "male"),
        _piper("ru", "ru_RU", "irina", "medium", "female"),
        _piper("de", "de_DE", "thorsten", "medium", "male"),
        _kokoro("int8", "kokoro-v1.0.int8.onnx", 115, 400,
                "int8 quantized, CPU only: its graph fails on DirectML (ConvTranspose).", gpu=False),
        _kokoro("fp32", "kokoro-v1.0.onnx", 337, 800, "Full precision; the variant to try on GPU.", gpu=True),
    ]
