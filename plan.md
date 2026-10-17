# TTS / STT Playground — Implementation Plan

**Date:** 2026-10-17
**Inputs:** `tts-stt-playground-spec.md`, the "tts stt backend" and "Web app" diagrams, and the decisions below.

---

## 0. Implementation status (2026-10-17, dev laptop)

Built and verified on the dev laptop (light CPU setup, ~0.5 GB venv, ~440 MB of models). Details in `docs/COMPATIBILITY.md`.

- **Phase 0:** done, except the GPU spike results, which need the RX 9070 XT machine (`backend/tools/gpu_probe.py` is ready).
- **Phase 1:** done. Engines:
  - STT: faster-whisper (tiny … large-v3-turbo) and Vosk small (EN/RU/DE)
  - TTS: Piper (EN/RU/DE) and Kokoro (int8 and fp32)
  - VAD: Silero
- **Phase 2:** done. Fixtures are synthetic (Piper-generated, `tools/make_fixtures.py`); real recordings are still to add.
- **Phase 3:** done. `tts_batch` is disabled with a reason, because no current engine batches natively.
- **Phase 4:** done for:
  - `live_endpointed` and `live_windowed` (faster-whisper)
  - `live_native` (Vosk)
  - the mic AudioWorklet
  - "fixture as mic" (real-time pace)

  sherpa-onnx is not added yet.
- **Phase 5 / 6:** not started. These need the GPU machine.
- **Deviations from the plan:**
  - Python 3.11 is used locally, because uv's managed Python 3.12 install failed on this machine. Use 3.12 on the GPU machine.
  - The UI primitives are hand-written in shadcn style instead of using the shadcn CLI, to keep dependencies small.

---

## 1. Decisions made (from the Q&A)

| Topic | Decision | Revisit when |
|---|---|---|
| Backend OS | **Native Windows 11** first | GPU support on Windows turns out too poor → add WSL2 Ubuntu + ROCm as a second environment |
| Process / venv model | **One backend process, one venv** (`uv`) | Two model families need conflicting dependencies → move engines into worker processes with separate venvs |
| Evaluation languages | **English, Russian, German** | — |
| Results persistence | **None.** 3 tabs only, metrics shown live in the UI | We want run history and comparisons → add SQLite and a Results tab |
| Hardware | AMD **RX 9070 XT** (gfx1201, 16 GB VRAM), ~30 GB RAM. CPU must always work | — |
| Frontend | Separate web app. Backend URL comes from `.env` (`VITE_API_URL`) | — |

> Note: the request said "RX 9700xt". I assume this is the **RX 9070 XT** named in the spec.

---

## 2. Architecture

### 2.1 Logical view

```
 ┌──────────────────────────┐
 │ Frontend (React + Vite)  │  separate app, VITE_API_URL=http://host:8000
 └────────────┬─────────────┘
              │ HTTP + WebSocket
 ┌────────────▼──────────────────────────────────────────────┐
 │ Backend (one process for now)                             │
 │  ┌───────────────┐   ┌──────────────┐   ┌──────────────┐  │
 │  │ gateway       │──▶│ stt module   │   │ tts module   │  │
 │  │ API, WS,      │──▶│ (facade +    │   │ (facade +    │  │
 │  │ sessions,     │   │  adapters)   │   │  adapters)   │  │
 │  │ event fan-out │   └──────┬───────┘   └──────┬───────┘  │
 │  └───────────────┘          └───── common ─────┘          │
 └───────────────────────────────────────────────────────────┘
```

### 2.2 Module independence rules (needed for the future 3-service split)

1. `stt` and `tts` **never import each other or `gateway`**.
2. `gateway` imports **only** `stt.service` / `tts.service` (a public facade) and their `schemas`. It never imports adapters or internals.
3. Facades are defined as `typing.Protocol` interfaces (`SttService`, `TtsService`). They take and return pydantic DTOs and raw audio bytes or numpy arrays, never engine objects. This keeps calls serializable.
4. Each module owns its **own model catalog, model directory, downloads, scheduler and events**. In the future, the STT service owns STT models on its own disk.
5. `common` is a library with no business logic: audio I/O and resampling, device probing, error types, event-bus interface, metrics helpers, HF download helper, and base schemas.
6. Enforce the rules with **`import-linter`** contracts that run in tests.

**Future split:** wrap `stt.service` in its own FastAPI app and add `RemoteSttService` (HTTP + WS client) to gateway. It implements the same Protocol, and the gateway code does not change. Same for TTS. The event bus becomes per-service streams that gateway aggregates.

### 2.3 Concurrency inside one process

- FastAPI / uvicorn event loop handles **only I/O** (HTTP, WS receive/send). It never runs blocking inference.
- Each **loaded model** gets a `ModelRunner` with:
  - a dedicated `ThreadPoolExecutor(max_workers = max_active)`. Most engines release the GIL during inference: CTranslate2, onnxruntime, torch, ggml.
  - a **bounded `asyncio.Queue`** (`max_queued`). When it is full, requests get a `QUEUE_FULL` error, never an unbounded wait.
  - an optional **batch collector** (`max_batch_size`, `max_wait_ms`). It is used only by adapters that have real native batching.
  - an explicit **intra-op thread count** per model (for example `OMP_NUM_THREADS`, ORT `intra_op_num_threads`, ctranslate2 `cpu_threads`). This avoids CPU oversubscription when several requests run in parallel.
- Per-session streaming state (buffers, VAD state, decoder state) lives in a `Session` object owned by the module and keyed by `session_id`. It is cleared on end, cancel, disconnect or timeout.
- Known limitation, to be documented: some Python-heavy engine code paths hold the GIL. If benchmarks show it, that is a reason to switch to worker processes.

### 2.4 Devices on native Windows (to be verified in Phase 0)

| Runtime path | AMD GPU on Windows | Used by |
|---|---|---|
| CPU (any engine) | — | everything |
| **PyTorch ROCm for Windows** (AMD wheels, Python 3.12) | Likely; RX 9070 XT is on AMD's Windows PyTorch matrix. **Verify** | Kokoro (torch), Qwen3-TTS, Qwen3-ASR (transformers), Chatterbox |
| **onnxruntime-directml** | Likely (DirectML is vendor-agnostic) | sherpa-onnx (if its DirectML provider works), Kokoro-ONNX, Piper, Silero VAD |
| **whisper.cpp + Vulkan** | Likely (ggml Vulkan backend) | whisper.cpp adapter |
| whisper.cpp + HIP | Possible with HIP SDK, more friction | optional |
| CTranslate2 (faster-whisper) | **No** (CUDA only) | faster-whisper = CPU only |
| vLLM | **No** on Windows | Qwen3-ASR native streaming = unavailable on Windows |

Single-venv consequences:
- Install **`onnxruntime-directml` instead of `onnxruntime`**. They provide the same module and conflict. The DirectML build includes the CPU EP.
- Install **one torch build**: the AMD ROCm Windows wheel if the Phase 0 spike passes, otherwise CPU torch.
- Device toggle semantics: `cpu` / `gpu` per model at load time. Switching device = unload + reload. **No silent fallback**: if `gpu` is requested and fails, the load fails with `DEVICE_UNAVAILABLE` and the reason. `auto` exists but always reports the device actually used.

---

## 3. Candidate models (filtered for EN / RU / DE)

Languages and licenses must be re-checked against the current model cards when each adapter is implemented. Below are working assumptions.

### STT

| Adapter | Langs | Modes it can honestly support | Device on Windows | Priority |
|---|---|---|---|---|
| **faster-whisper** (small / medium / large-v3-turbo) | EN RU DE | `file_single`, `file_batch` (native `BatchedInferencePipeline`), `live_endpointed`, `live_windowed` | CPU | **P1, first baseline** |
| **whisper.cpp** (same checkpoints, GGML) | EN RU DE | `file_single`, `live_endpointed`, `live_windowed` (batching: verify) | CPU, **GPU via Vulkan** | P2, first GPU STT |
| **sherpa-onnx streaming zipformer** | EN, RU (verify a streaming RU model), DE: verify | `live_native`; check whether its server API supports multi-stream batching (`live_batched`) | CPU, DirectML: verify | P2, first native streaming |
| **Vosk** (Kaldi) | EN RU DE | `live_native` | CPU | P3, simple native-streaming fallback with all 3 languages |
| **Qwen3-ASR 0.6B** (transformers) | EN RU DE | `file_single`, `file_batch`. `live_native` **unavailable on Windows** (needs vLLM) | CPU, GPU via torch-ROCm: verify | P3 |
| Parakeet TDT 0.6B v3 (via sherpa-onnx / onnx) | EN RU DE + others | `file_single` (offline) | CPU, DirectML: verify | optional |
| Moonshine streaming | EN only (verify) | `live_native` | CPU | optional |

### TTS

| Adapter | Langs | Modes | Device on Windows | Priority |
|---|---|---|---|---|
| **Piper** | EN RU DE (many voices) | `tts_file`; `tts_stream` = *sentence-segmented* (labelled so) | CPU (ONNX), DirectML: verify | **P1, CPU baseline for all 3 langs.** License: piper1 is GPL-3. OK for a personal playground, but note it |
| **Kokoro 82M** | **EN only** of our 3 | `tts_file`; `tts_stream` = sentence-segmented generator; `tts_batch`: verify | CPU, GPU via torch-ROCm or ONNX-DirectML | P1 |
| **Qwen3-TTS 0.6B** | EN RU DE | `tts_file`, `tts_stream` (**model-native** streaming, verify in the chosen runtime), `tts_batch` (per official examples) | GPU via torch-ROCm: verify; CPU likely slow | P3 |
| **Chatterbox Multilingual** | EN RU DE | `tts_file`, possibly `tts_stream` (verify); voice cloning (consented references only) | GPU via torch-ROCm: verify | P3 (torch-pin conflict risk → may trigger the venv split) |

### VAD
- **Silero VAD (ONNX)** on the server, P2. Client-side VAD comes later (Phase 6).

### Honest streaming labels (shown in the UI)
- STT: `live_native` (stateful model) vs `live_windowed` (re-running an offline model on rolling windows) vs `live_endpointed` (VAD, then offline inference).
- TTS: `model_streaming` (audio produced incrementally by the model) vs `segment_streaming` (text split into sentences, each synthesized fully) vs `output_chunked` (complete audio sent in network chunks).

---

## 4. Capability registry and model catalog

Each module has a **catalog**: a static Python/YAML list of known models. The **registry** merges catalog entries with live state. One entry looks like this:

```jsonc
{
  "id": "stt.faster-whisper.large-v3-turbo",
  "task": "stt",
  "name": "Whisper large-v3-turbo (faster-whisper)",
  "engine": "faster-whisper", "engine_version": "1.x.y",
  "source": {"hf_repo": "...", "revision": "..."},
  "params": "809M", "disk_size_mb": 1600, "est_ram_mb": 2000, "est_vram_mb": null,
  "languages": ["en","ru","de", "..."],
  "voices": null,                         // TTS only: [{id, name, language, gender}]
  "devices_supported": ["cpu"],
  "devices_available_now": ["cpu"],
  "modes": {"file_single": true, "file_batch": true, "live_native": false,
            "live_windowed": true, "live_endpointed": true, "live_batched": false},
  "streaming_kind": null,                 // TTS: model_streaming | segment_streaming | output_chunked
  "native_batching": true,
  "license": "MIT", "license_note": "...",
  "notes": "...",
  "state": {
    "download": "not_downloaded | downloading | downloaded | error",
    "download_progress": 0.0,
    "path": "D:\\models\\stt\\faster-whisper\\large-v3-turbo",
    "load": "unloaded | loading | loaded | unloading | error",
    "device": "cpu",
    "runtime": "ctranslate2 4.x / int8",
    "ram_mb": 1850, "vram_mb": null,
    "runner": {"max_active": 1, "max_queued": 16, "max_batch_size": 8, "max_wait_ms": 50,
               "active": 0, "queued": 0}
  },
  "unavailable_reason": null
}
```

Unsupported mode or device combinations are disabled in the UI **and** rejected by the API (`MODE_UNSUPPORTED`, `DEVICE_UNAVAILABLE`).

**Memory reporting on Windows/AMD:** RAM comes from the `psutil` RSS delta around the load. VRAM is measured per process with the Windows PDH counter `\GPU Process Memory(<pid>*)\Dedicated Usage`. That counter works for Vulkan, DirectML and ROCm. For torch-ROCm models, `torch.cuda.mem_get_info` is used as well. The UI labels these values as approximate.

---

## 5. API and WebSocket contract (v0)

All errors use one shape: `{"error": {"code": "QUEUE_FULL", "message": "...", "details": {...}, "request_id": "..."}}`.
Codes: `MODEL_NOT_FOUND`, `MODEL_NOT_DOWNLOADED`, `MODEL_NOT_LOADED`, `MODE_UNSUPPORTED`, `DEVICE_UNAVAILABLE`, `QUEUE_FULL`, `INVALID_AUDIO`, `INVALID_REQUEST`, `INFERENCE_FAILED`, `DOWNLOAD_FAILED`, `OUT_OF_MEMORY`, `CANCELLED`, `INTERNAL`.

### HTTP
| Method & path | Purpose |
|---|---|
| `GET /api/health` | Status, versions, detected devices (CPU info, GPU name, available runtimes) |
| `GET /api/models?task=stt\|tts` | Catalog + state (section 4) |
| `POST /api/models/{id}/download` | Start a download (progress arrives via the events WS) |
| `DELETE /api/models/{id}/files` | Delete files from disk (UI asks for confirmation; refused while loaded) |
| `POST /api/models/{id}/load` `{device, runner_config}` | Load into memory on cpu/gpu |
| `POST /api/models/{id}/unload` | Unload |
| `PATCH /api/models/{id}/runner` | Change max_active / queue / batch settings (applies live or needs a reload; the response says which) |
| `POST /api/stt/transcribe` (multipart: file + options JSON) | `file_single` |
| `POST /api/stt/batch` (multipart: N files) | `file_batch`: one explicit batch, per-item results + timings |
| `POST /api/tts/synthesize` | `tts_file` → WAV + metrics (metrics in a JSON response with base64 audio, or headers; decide in Phase 3) |
| `POST /api/tts/batch` | `tts_batch` |

Every inference response includes **server timings**: `queue_wait_ms`, `compute_ms`, `batch_id`, `batch_size`, `audio_duration_ms`, `rtf`, `device`. The client measures end-to-end time itself. Comparing the two separates network/decode time from compute.

### WebSockets
- **`WS /ws/events`** (global): model state changes, download progress, and **all server errors and warnings**. A logging handler forwards ERROR/WARNING records with source module, code, message, traceback and `request_id`/`session_id`. This feeds the error panel.
- **`WS /ws/stt`**: one connection per STT row/session.
  ```
  C→S {"type":"start","model_id":..,"mode":"live_native|live_windowed|live_endpointed",
       "language":"ru","sample_rate":16000,"format":"pcm_s16le","frame_ms":40,
       "vad":{"policy":"server","silence_ms":700,"pre_roll_ms":300},
       "window":{"size_ms":5000,"stride_ms":1000}}
  S→C {"type":"ready","session_id":..,"device":"cpu"}
  C→S <binary PCM frames>   (seq numbers in a 4-byte header)
  S→C {"type":"vad","state":"speech_start","at_ms":..}
  S→C {"type":"transcript.partial","text":..,"revision":n,"at_ms":..}
  S→C {"type":"transcript.final","text":..,"start_ms":..,"end_ms":..}
  C→S {"type":"end_input"} | {"type":"cancel"}
  S→C {"type":"session.completed","metrics":{..}} | {"type":"error",..}
  ```
- **`WS /ws/tts`**: one per TTS row when streaming.
  ```
  C→S {"type":"start","model_id":..,"voice":..,"language":..,"text":..,"speed":1.0}
  S→C {"type":"audio.meta","sample_rate":24000,"format":"pcm_s16le","streaming_kind":"segment_streaming"}
  S→C <binary: 4-byte seq + PCM chunk> ...
  S→C {"type":"done","metrics":{"time_to_first_chunk_ms":..,"total_ms":..,"audio_ms":..,"rtf":..}}
  ```

The full protocol is documented in `docs/PROTOCOL.md` and versioned (`"protocol": 0` in `ready`).

---

## 6. Frontend

**Stack:** Vite + React + TypeScript, Tailwind + shadcn/ui, TanStack Query (REST), Zustand (rows and session state), Vitest.
**Config:** `frontend/.env` → `VITE_API_URL=http://localhost:8000`. The WS URL is derived from it. The header shows the connected backend URL and a health dot. The backend's `CORS_ORIGINS` comes from its own `.env`.

### Global layout
- Top: tabs **Management | TTS | STT**, plus backend URL/status.
- Bottom (on every tab): **Error panel** fed by `/ws/events` and by failed requests. Shows time, source (stt/tts/gateway), code, message and related model/session, with the traceback expandable. Has filter and clear. Collapsible, with an unread-count badge.

### Management tab (two columns: TTS models | STT models)
Each model is a card showing:
- name, engine + version, params, disk size, estimated RAM/VRAM, languages, voices (TTS), capabilities as badges, license, notes
- devices supported (CPU / GPU), with the **unavailable reason** shown when GPU is not possible
- **Download** button with a progress bar (when not downloaded)
- **Delete** button → confirmation dialog; shows the **on-disk path** (with a copy button)
- **Load** button with a **CPU/GPU toggle**, and **Unload**
- when loaded: actual device/runtime, measured RAM/VRAM, runner settings (max active, queue size, batch size, batch wait), live active/queued counters

### STT tab: a list of independent "client rows" + an **Add row** button
Each row is one simulated client with its own WS/HTTP session:
- **Left:** model select (loaded models only) · mode toggles enabled from capabilities (`file_single`, `file_batch`, `live_endpointed`, `live_windowed`, `live_native`) · language · mode-specific settings (frame ms, window/stride, VAD silence ms) · audio source: **upload file(s)**, **fixture** (built-in clips), or **mic**: hold-to-talk button (or toggle). Includes a level meter.
- **Right top:** result. Live partial text (grey, revisable) + committed final text, built incrementally as messages arrive. Small collapsible event timeline (frames sent, VAD start/end, queued/started, partial/final).
- **Right bottom:** metrics (client side): time from first audio sent → first partial, → first final, → completed. Server side: queue wait, compute, batch size, RTF, device.
- Row actions: send / stop / cancel / duplicate / remove.
- Tab-level: **"Run all rows"** starts every row at the same moment, which is the concurrency experiment. **"Clone row ×N"** creates N identical clients quickly.

### TTS tab: same structure as STT
Each row: model · voice · language · speed (if supported) · mode (`tts_file`, `tts_stream`, `tts_batch`, with the streaming kind shown) · text box with presets (short/medium/long sentences in EN/RU/DE) · **Generate** · audio player with incremental playback for streams · download WAV · metrics (time to first audio chunk, total synthesis, audio duration, RTF, queue wait, device). Includes **Add row**, **Run all rows** and **Clone ×N**.

### Browser audio
- Mic capture: `getUserMedia` → **AudioWorklet** → resample from the device rate to 16 kHz → Int16 → WS frames (configurable 20–100 ms). Hold-to-talk in file mode records the same PCM locally and uploads it as WAV.
- TTS stream playback: an AudioWorklet ring-buffer PCM player. It reports when the **first sample actually plays**, separately from when the first chunk arrives.
- Mic works on `http://localhost`. A remote backend with a local frontend is fine. A frontend served from another host needs HTTPS.

---

## 7. Repository layout

```
playground-tts-stt/
├── plan.md
├── tts-stt-playground-spec.md
├── README.md                      # Windows setup + run commands
├── backend/
│   ├── pyproject.toml             # uv, Python 3.12, single venv
│   ├── .env.example               # HOST, PORT, CORS_ORIGINS, MODELS_DIR, LOG_LEVEL, ...
│   ├── src/
│   │   ├── common/                # audio (decode via PyAV, resample via soxr), devices, errors,
│   │   │                          # events, metrics, hf_download, schemas_base
│   │   ├── stt/
│   │   │   ├── service.py         # SttService Protocol + LocalSttService (public facade)
│   │   │   ├── schemas.py
│   │   │   ├── catalog.py
│   │   │   ├── registry.py
│   │   │   ├── runner.py          # ModelRunner: queue, executor, batch collector
│   │   │   ├── sessions.py        # live session state, windowing, endpointing
│   │   │   ├── vad/               # silero (onnx)
│   │   │   └── adapters/          # faster_whisper.py, whisper_cpp.py, sherpa.py, vosk.py, qwen_asr.py
│   │   ├── tts/
│   │   │   ├── service.py, schemas.py, catalog.py, registry.py, runner.py
│   │   │   └── adapters/          # piper.py, kokoro.py, qwen_tts.py, chatterbox.py
│   │   └── gateway/
│   │       ├── app.py             # FastAPI app factory, CORS, error handlers
│   │       ├── routes/            # health, models, stt, tts
│   │       └── ws/                # events, stt_stream, tts_stream
│   ├── tests/                     # pytest; fake adapters live here only
│   └── tools/                     # spike scripts (gpu_probe.py, ...)
├── frontend/
│   ├── .env.example               # VITE_API_URL
│   └── src/
│       ├── api/                   # REST client, WS clients, protocol types
│       ├── audio/                 # mic worklet, resampler, pcm player worklet, wav encode
│       ├── features/management/
│       ├── features/stt/
│       ├── features/tts/
│       └── components/            # ErrorPanel, layout, shared UI
├── fixtures/
│   └── audio/{en,ru,de}/          # 5s / 10s / 30s clips + .txt references (CC0 / CC-BY sources)
└── docs/
    ├── COMPATIBILITY.md           # model × device × mode matrix, as actually tested on this machine
    └── PROTOCOL.md
```

Models are stored under `MODELS_DIR` (default `./models`, gitignored), as `MODELS_DIR/stt/<engine>/<model>` and `MODELS_DIR/tts/...`. Nothing is downloaded at import time or in tests.

---

## 8. Phases

Every phase ends with something runnable and tested on this Windows machine.

### Phase 0: Scaffold + Windows GPU spike
- [ ] `uv` backend skeleton (Python 3.12), FastAPI app, `/api/health`, `.env` config, logging → `/ws/events`, structured error handling.
- [ ] Vite/React frontend skeleton: 3 tabs, backend URL from `.env`, health indicator, **error panel** wired to `/ws/events`.
- [ ] `import-linter` contracts for module boundaries. pytest and Vitest running.
- [ ] **GPU spike** (`backend/tools/gpu_probe.py`). For each path, report works / fails with the reason:
  - torch ROCm Windows wheel: `torch.cuda.is_available()`, a matmul, VRAM query
  - onnxruntime-directml: DirectML EP creates a session and runs a tiny model
  - whisper.cpp Vulkan build (prebuilt release binaries or `pywhispercpp` built with `GGML_VULKAN=1`): transcribe a fixture
  - PDH GPU-memory counter readable for our PID
- [ ] Write the results into `docs/COMPATIBILITY.md`. **This decides the torch build in the single venv.**

**Done when:** both apps start, the frontend shows the backend status, a deliberately triggered error shows up in the error panel, and the GPU spike results are documented.

### Phase 1: Management tab + first two CPU models
- [ ] Catalog/registry, download (HF hub with progress events), delete with confirmation + path, load/unload with device selection, RAM/VRAM measurement, runner settings.
- [ ] Adapters: **faster-whisper** (CPU) and **Piper** (CPU, EN/RU/DE voices). **Kokoro** (EN) is the second TTS.
- [ ] Management UI as in the mockup.

**Done when:** I can download → load → see memory → unload → delete each model from the UI, and failures appear in the error panel.

### Phase 2: STT tab, offline modes
- [ ] Rows UI, upload/fixture/hold-to-talk recording (WAV upload), `file_single`.
- [ ] `file_batch`: explicit multi-file batch from one row (faster-whisper native batching).
- [ ] Server-side **dynamic batching** across rows (batch collector with `max_batch_size` / `max_wait_ms`). Each response reports `batch_id` and `batch_size`, so you can see which requests were grouped.
- [ ] Bounded queue + `QUEUE_FULL`; "Run all rows" / "Clone ×N"; client and server metrics in each row.
- [ ] Fixtures: 5s / 10s / 30s clips in EN/RU/DE with reference text, so the head-of-line batching experiment from the spec (§5) can be run.

### Phase 3: TTS tab
- [ ] Rows UI, `tts_file` (Piper, Kokoro), WAV playback + download.
- [ ] `tts_stream` via `/ws/tts` with the AudioWorklet PCM player. Piper/Kokoro are labelled **segment_streaming**.
- [ ] `tts_batch` where an adapter supports it natively. Otherwise it is disabled in the UI and the reason is shown.
- [ ] Metrics: time to first chunk, time to first *played* sample, total, RTF.

### Phase 4: Live STT
- [ ] Mic AudioWorklet → `/ws/stt` PCM frames, level meter, frame-size control.
- [ ] Silero VAD on the server with pre-roll/tail buffers, and VAD events in the timeline.
- [ ] `live_endpointed` (VAD → offline model) and `live_windowed` (rolling window + overlap + dedup of committed text) for faster-whisper.
- [ ] First **native streaming** adapter: sherpa-onnx (EN + RU model) and/or Vosk (EN/RU/DE). Partial vs final, revisions, cancel/disconnect cleanup.
- [ ] Multi-row live test: several rows streaming fixtures in parallel ("play fixture as mic" option), verifying no transcript leaks between rows.

### Phase 5: GPU models
- [ ] whisper.cpp adapter with Vulkan (and CPU), on the same checkpoint as faster-whisper for CPU vs GPU comparison.
- [ ] Kokoro on GPU (torch-ROCm or ONNX DirectML, whichever the spike showed works).
- [ ] Qwen3-TTS 0.6B (native streaming if the runtime provides it), Qwen3-ASR 0.6B offline. Chatterbox Multilingual.
- [ ] If torch/transformers pins conflict → **trigger the venv split** (see §9). Until then, conflicting models are marked unavailable with the reason.

### Phase 6: Advanced experiments
- [ ] `live_batched` (multi-stream batching) **only** for an engine confirmed to support it (sherpa-onnx is the candidate).
- [ ] Client-side VAD and hybrid VAD policies.
- [ ] `file_chunked` experiment (one long file split with overlap).
- [ ] WER/CER against fixture references (computed live, shown in the row; still no persistence).

### Later (not planned in detail)
- WSL2 Ubuntu + ROCm environment, if Windows GPU support is insufficient.
- Split into 3 services (gateway / stt / tts) using the facade Protocols.
- Results persistence (SQLite) + Results tab + CSV/JSON export.
- STT → LLM → TTS loop, WebRTC/LiveKit, React Native clients.

---

## 9. Planned escape hatches

| Trigger | Change |
|---|---|
| Dependency conflict between model families | Engine families move into worker subprocesses with their own venvs. The ModelRunner talks to them over local IPC (stdin/stdout msgpack or a localhost socket). Facades stay the same. |
| GIL contention visible in parallel benchmarks | Same worker-process move for the affected engine. |
| GPU path unusable on Windows for key models | Add WSL2 Ubuntu backend environment. The frontend points to it via `VITE_API_URL`; no code change needed. |
| Need to scale or deploy separately | Split into services via the `Remote*Service` clients (§2.2). |

---

## 10. Testing strategy

- **Backend unit tests:** audio conversion/resampling, runner queue/backpressure, batch collector grouping, session lifecycle and cleanup, error mapping, all using **fake adapters in `tests/`** (never exposed in the app).
- **Contract tests:** REST and WS message shapes against pydantic schemas. TS types are generated from the OpenAPI schema (`openapi-typescript`) to keep frontend and backend in sync.
- **Model smoke tests** (opt-in marker `-m models`, need downloaded weights): each adapter transcribes or synthesizes one fixture on each available device.
- **Frontend:** Vitest for the protocol client, resampler, PCM framing and row state. A manual checklist per phase for audio UX.

---

## 11. Remaining open questions (non-blocking; defaults in bold)

1. **Models directory location:** **`./models` inside the repo (gitignored)**, or a separate drive such as `D:\models`? Large models (Qwen, Chatterbox, whisper-large) add up to tens of GB.
2. **Piper license (GPL-3 for piper1):** **fine for a personal playground**? If the code may become part of a commercial product later, we would pick a different CPU TTS for RU/DE.
3. **Mic UX:** hold-to-talk **and** a toggle (click to start/stop), or only hold-to-talk? Default: **both**.
4. **Fixtures:** **use public CC0/CC-BY clips** (LibriSpeech / Multilingual LibriSpeech / Common Voice), or will you record your own EN/RU/DE samples? Your own voice is more realistic for your use case.
5. **Backend exposure:** **localhost/LAN only, no auth** for now? If the backend will be reachable from other machines, we need at least a shared token + HTTPS.
