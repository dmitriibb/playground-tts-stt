"""Known STT models. Sizes and memory are estimates; measured values appear after load."""

from __future__ import annotations

from common.downloads import DownloadSource, HfFiles, UrlFile
from common.onnx import ort_devices
from common.registry import ModelSpec
from common.schemas import RunnerConfig
from stt.adapters.faster_whisper import FasterWhisperAdapter
from stt.adapters.vosk import VoskAdapter
from stt.vad import SileroVadAdapter

WHISPER_LANGS = ["en", "ru", "de", "fr", "es", "it", "uk", "pl", "…99"]
_FW_PATTERNS = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]

_FW_MODES = {
    "file_single": True, "file_batch": True, "live_native": False, "live_windowed": True,
    "live_endpointed": True, "live_batched": False, "file_chunked": False,
}
_FW_NOTES = {
    "file_batch": "Native batching for clips up to 30 s (one Whisper window)",
    "file_single": "Clips up to 30 s are dynamically batched across clients when max_batch_size > 1",
    "live_windowed": "Pseudo-streaming: re-runs the offline model on a rolling window",
    "live_endpointed": "VAD (Silero, must be loaded) cuts utterances, then offline inference",
    "live_native": "Whisper is not a streaming model",
    "live_batched": "No multi-stream batching; endpointed utterances can still share dynamic batches",
    "file_chunked": "Planned (Phase 6)",
}


def _faster_whisper(size: str, repo: str, params: str, disk_mb: float, ram_mb: float) -> ModelSpec:
    return ModelSpec(
        id=f"stt.faster-whisper.{size}",
        task="stt",
        name=f"Whisper {size} (faster-whisper)",
        engine="faster-whisper",
        engine_package="faster-whisper",
        engine_module="faster_whisper",
        adapter_factory=lambda spec: FasterWhisperAdapter(),
        source=DownloadSource(hf=HfFiles(repo=repo, patterns=_FW_PATTERNS)),
        languages=WHISPER_LANGS,
        modes=_FW_MODES,
        mode_notes=_FW_NOTES,
        params=params,
        disk_size_mb=disk_mb,
        est_ram_mb=ram_mb,
        devices_supported=["cpu"],
        native_batching=True,
        default_runner=RunnerConfig(max_active=1, max_queued=32, max_batch_size=4, max_wait_ms=50),
        license="MIT",
        notes="CTranslate2 int8 on CPU. CTranslate2 has no AMD GPU backend; use whisper.cpp (Vulkan) for GPU.",
    )


def _vosk(lang: str, name: str, disk_mb: float) -> ModelSpec:
    return ModelSpec(
        id=f"stt.vosk.small-{lang}",
        task="stt",
        name=f"Vosk small {lang.upper()} ({name})",
        engine="vosk",
        engine_package="vosk",
        engine_module="vosk",
        adapter_factory=lambda spec: VoskAdapter(lang),
        source=DownloadSource(urls=[UrlFile(url=f"https://alphacephei.com/vosk/models/{name}.zip",
                                            filename=f"{name}.zip", extract=True)]),
        languages=[lang],
        modes={"file_single": True, "file_batch": False, "live_native": True, "live_windowed": False,
               "live_endpointed": False, "live_batched": False, "file_chunked": False},
        mode_notes={"live_native": "Stateful Kaldi recognizer: true streaming with partials",
                    "file_batch": "No native batching"},
        params="small (Kaldi)",
        disk_size_mb=disk_mb,
        est_ram_mb=300,
        devices_supported=["cpu"],
        default_runner=RunnerConfig(max_active=4, max_queued=64),
        license="Apache-2.0",
        notes="Lightweight native-streaming baseline. Lower accuracy than Whisper.",
    )


def catalog() -> list[ModelSpec]:
    return [
        _faster_whisper("tiny", "Systran/faster-whisper-tiny", "39M", 75, 250),
        _faster_whisper("base", "Systran/faster-whisper-base", "74M", 145, 400),
        _faster_whisper("small", "Systran/faster-whisper-small", "244M", 484, 900),
        _faster_whisper("medium", "Systran/faster-whisper-medium", "769M", 1530, 2200),
        _faster_whisper("large-v3-turbo", "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "809M", 1620, 2400),
        _vosk("en", "vosk-model-small-en-us-0.15", 40),
        _vosk("ru", "vosk-model-small-ru-0.22", 45),
        _vosk("de", "vosk-model-small-de-0.15", 45),
        ModelSpec(
            id="vad.silero.v5",
            task="vad",
            name="Silero VAD v5 (ONNX)",
            engine="silero-vad (onnxruntime)",
            engine_package="onnxruntime-directml",
            engine_module="onnxruntime",
            adapter_factory=lambda spec: SileroVadAdapter(),
            source=DownloadSource(urls=[UrlFile(
                url="https://raw.githubusercontent.com/snakers4/silero-vad/v5.1.2/src/silero_vad/data/silero_vad.onnx",
                filename="silero_vad.onnx")]),
            languages=["any"],
            modes={},
            params="~2M",
            disk_size_mb=2.2,
            est_ram_mb=30,
            devices_supported=["cpu", "gpu"],
            devices_now=ort_devices,
            license="MIT",
            notes="Voice activity detection. Load it to enable live_endpointed in the STT tab.",
        ),
    ]
