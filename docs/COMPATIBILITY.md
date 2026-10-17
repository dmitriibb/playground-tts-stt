# Compatibility matrix (as actually tested)

Fill one section per machine. "✓" = ran end to end through the API, "✕" = fails (reason given),
"—" = not applicable, "?" = not tested yet.

## Dev laptop — 2026-10-17

Ryzen 7 5800U (8C/16T), 15 GB RAM, AMD Radeon integrated GPU, Windows 11, Python 3.11.9,
onnxruntime-directml 1.24.4, ctranslate2 4.8.3, no torch.

`tools/gpu_probe.py`: DirectML EP ✓ (ran Silero VAD), PDH VRAM counter ✓, torch-ROCm — not installed,
whisper.cpp Vulkan — not installed.

| Model | CPU | GPU (DirectML) | Modes verified | Notes |
|---|---|---|---|---|
| faster-whisper tiny | ✓ | — (CTranslate2 has no AMD backend) | file_single, file_batch (native, 3 langs auto-detected), live_endpointed, live_windowed, dynamic batching across 5 clients (4 batched + 1 queued) | RTF ≈ 0.03–0.10 |
| Vosk small EN | ✓ | — | file_single, live_native (partials + final) | RTF ≈ 0.2 |
| Silero VAD v5 | ✓ | ✓ | used by live_endpointed | |
| Piper en_US lessac / ru_RU irina / de_DE thorsten (medium) | ✓ | ✓ (en_US tested, RTF 0.62 on the iGPU vs 0.06 on CPU) | tts_file, tts_stream (segment_streaming) | VRAM measured ≈ 61 MB |
| Kokoro v1.0 int8 | ✓ | ✕ `ConvTranspose` "The parameter is incorrect" in DirectML | tts_file, tts_stream | marked CPU-only in the catalog |
| Kokoro v1.0 fp32 | ? | ? | | try on the RX 9070 XT |
| faster-whisper base/small/medium/large-v3-turbo | ? | — | | not downloaded here (disk space) |
| Vosk small RU/DE | ? | — | | |

## RX 9070 XT machine — TODO

Run `tools/gpu_probe.py`, then fill the same table, plus:

- torch ROCm Windows wheel: `torch.cuda.is_available()`, matmul TFLOPS, VRAM — decides the single-venv torch build
- whisper.cpp Vulkan build on a fixture (Phase 5 adapter)
- Kokoro fp32 and Piper on DirectML
