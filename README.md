# playground-tts-stt

A playground for testing TTS and STT models and the ways to serve them: file vs. streaming,
dynamic batching, and many parallel clients. Runs on CPU and on AMD GPUs (DirectML / ROCm / Vulkan).

- `backend/` — FastAPI, one process with three independent modules: `gateway` (HTTP + WS),
  `stt`, `tts`, plus the `common` library. Module boundaries are enforced by `import-linter`.
- `frontend/` — React + Vite web app with 3 tabs (Management, TTS, STT) and an error panel.
  It connects to any backend through `VITE_API_URL`.
- `fixtures/audio/` — EN/RU/DE test clips (currently synthetic, generated with Piper).
- `plan.md` — design and phases. `docs/PROTOCOL.md` — API/WS contract. `docs/COMPATIBILITY.md` — what was tested where.

## Quick start (Windows)

Requirements: Python 3.11 or 3.12, Node 20+, [uv](https://docs.astral.sh/uv/) (`pip install uv`).

```bash
cd backend
uv sync --extra cpu          # ~0.5 GB venv: FastAPI + faster-whisper, Vosk, Piper, Kokoro (ONNX), onnxruntime-directml
copy .env.example .env       # HOST, PORT, CORS_ORIGINS, MODELS_DIR, FIXTURES_DIR
.venv\Scripts\python -m gateway
```

```bash
cd frontend
npm install
copy .env.example .env       # VITE_API_URL=http://127.0.0.1:8000
npm run dev                  # http://127.0.0.1:5173
```

Then in the **Management** tab: download a model, load it on CPU or GPU, and use it in the **STT** / **TTS** tabs.
Models are stored under `MODELS_DIR` (default `backend/models`, gitignored).

### Light setup vs. the GPU machine

The `cpu` extra is deliberately small and works on any machine. On the RX 9070 XT machine:

1. `uv sync --extra cpu` (same as above; prefer Python 3.12, AMD's ROCm Windows wheels target it).
2. Run the GPU spike: `.venv\Scripts\python tools\gpu_probe.py` and record results in `docs/COMPATIBILITY.md`.
3. Install the AMD ROCm PyTorch wheel if the spike says so, then add the Phase 5 adapters
   (whisper.cpp Vulkan, Kokoro fp32 on GPU, Qwen3-ASR/TTS, Chatterbox). Large models
   (`faster-whisper large-v3-turbo`, `medium`, Kokoro fp32) are already in the catalog.

## Tests

```bash
cd backend && .venv\Scripts\python -m pytest     # unit + API + WS tests with fake engines, import contracts
cd frontend && npm test                          # resampler, framing, protocol, error store
cd frontend && npm run typecheck
```

Regenerate the frontend API types after changing backend schemas (backend must be running):
`npm run gen:api`.

## Useful tools

- `backend/tools/make_fixtures.py` — synthesizes EN/RU/DE fixture clips through the running backend (Piper voices must be loaded).
- `backend/tools/gpu_probe.py` — checks torch-ROCm, ONNX Runtime GPU provider, whisper.cpp Vulkan and the VRAM counter.
- `POST /api/debug/error?kind=internal|app|warning` — fails on purpose, to see errors in the UI error panel.
