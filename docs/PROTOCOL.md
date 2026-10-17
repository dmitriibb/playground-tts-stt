# API and WebSocket protocol (v0)

The OpenAPI schema is served at `GET /openapi.json` (interactive docs at `/docs`). The frontend
types in `frontend/src/api/schema.d.ts` are generated from it (`npm run gen:api`). WebSocket messages
are not in OpenAPI; they are described here and in `frontend/src/api/protocol.ts`.

## Errors

Every error has one shape:

```json
{"error": {"code": "QUEUE_FULL", "message": "...", "details": {}, "request_id": "..."}}
```

Codes: `MODEL_NOT_FOUND`, `MODEL_NOT_DOWNLOADED`, `MODEL_NOT_LOADED`, `MODEL_BUSY`, `MODE_UNSUPPORTED`,
`DEVICE_UNAVAILABLE`, `ENGINE_UNAVAILABLE`, `QUEUE_FULL`, `INVALID_AUDIO`, `INVALID_REQUEST`,
`INFERENCE_FAILED`, `DOWNLOAD_FAILED`, `OUT_OF_MEMORY`, `CANCELLED`, `INTERNAL`.

The client may send `X-Request-ID`; the server echoes it (or generates one) in the response header,
the error body and the server log events, so the UI merges both into one error panel entry.
On WebSockets the session id plays the same role.

## HTTP

| Method & path | Purpose |
|---|---|
| `GET /api/health` | status, version, protocol, models dir, loaded models, CPU/GPU/runtime info |
| `GET /api/models?task=stt\|tts` | catalog + live state (`ModelInfo`) |
| `GET /api/models/{id}` | one model |
| `POST /api/models/{id}/download` | start a download (202); progress via `/ws/events` |
| `DELETE /api/models/{id}/files` | delete files (refused while loaded: `MODEL_BUSY`) |
| `POST /api/models/{id}/load` | `{"device": "cpu"\|"gpu", "threads": 0, "runner": {...}}` |
| `POST /api/models/{id}/unload` | unload |
| `PATCH /api/models/{id}/runner` | `{max_active, max_queued, max_batch_size, max_wait_ms}` — all apply live |
| `POST /api/stt/transcribe` | multipart `file` + `options` JSON `{model_id, language, beam_size}` → `file_single` |
| `POST /api/stt/batch` | multipart `files[]` + `options` → `file_batch` (one native batch, clips ≤ 30 s for Whisper) |
| `POST /api/tts/synthesize` | `{model_id, text, voice, language, speed}` → base64 WAV + timings (`tts_file`) |
| `POST /api/tts/batch` | `{model_id, items[]}` → `tts_batch` (only engines with native batching) |
| `GET /api/fixtures` | built-in clips with reference text |
| `GET /api/fixtures/{lang}/{name}` | clip bytes |

Every inference response carries **server timings**:
`model_id, device, queue_wait_ms, compute_ms, batch_id, batch_size, audio_duration_ms, rtf`.
Requests that share a `batch_id` were computed together. The client measures end-to-end time itself.

## `WS /ws/events`

```
S→C {"type":"hello","protocol":0,"server_time":...}
S→C {"type":"model.state","seq":..,"ts":..,"source":"stt|tts","data":{"model":ModelInfo}}
S→C {"type":"download.progress","source":..,"data":{"model_id","progress","downloaded_mb","total_mb"}}
S→C {"type":"log","source":"stt|tts|gateway|engine|common","data":{"level":"error|warning","message",
     "code"?,"request_id"?,"session_id"?,"model_id"?,"traceback"?}}
C→S "ping"  →  S→C {"type":"pong"}
```

## `WS /ws/stt` — one live session per connection

```
C→S {"type":"start","model_id":..,"mode":"live_native|live_windowed|live_endpointed",
     "language":"en"|null,"sample_rate":16000,"format":"pcm_s16le","frame_ms":40,"beam_size":1,
     "vad":{"model_id":"vad.silero.v5","threshold":0.5,"silence_ms":700,"pre_roll_ms":300,
            "min_speech_ms":250,"max_segment_ms":15000,"partial_interval_ms":0},
     "window":{"size_ms":6000,"stride_ms":1000,"tail_ms":1500}}
S→C {"type":"ready","session_id":..,"protocol":0,"model_id":..,"mode":..,"device":"cpu"}
C→S binary: uint32 LE sequence number + PCM s16le 16 kHz mono
S→C {"type":"vad","state":"speech_start|speech_end","at_ms":..}               (endpointed)
S→C {"type":"transcript.partial","text":..,"revision":n,"at_ms":..,"timings"?}
S→C {"type":"transcript.final","text":..,"start_ms":..,"end_ms":..,"at_ms":..,"timings"?}
C→S {"type":"end_input"}   → remaining audio is processed, then
S→C {"type":"session.completed","metrics":{audio_received_ms, inference_calls, compute_ms_total,
     queue_wait_ms_total, partials, finals, max_batch_size, rtf, device, model_id, mode}}
C→S {"type":"cancel"}      → S→C {"type":"cancelled"}
S→C {"type":"error","error":{...}}
```

`at_ms`, `start_ms`, `end_ms` are positions on the audio timeline of the session (ms of audio received).
`live_endpointed` requires the Silero VAD model to be loaded. Mode honesty:

- `live_native` — a stateful streaming recognizer (Vosk).
- `live_windowed` — an offline model re-run on a rolling window; words older than `tail_ms` are committed.
- `live_endpointed` — VAD cuts utterances, each is transcribed by an offline model. Utterances from
  different sessions can share a dynamic batch (see `timings.batch_size`).

## `WS /ws/tts` — streaming synthesis

```
C→S {"type":"start","model_id":..,"text":..,"voice":..,"language":..,"speed":1.0}
S→C {"type":"audio.meta","sample_rate":22050,"format":"pcm_s16le","streaming_kind":"segment_streaming",
     "segments":n,"device":"cpu"}
S→C {"type":"segment","index":i,"text":..,"audio_ms":..,"seq":k,"timings":{...}}
S→C binary: uint32 LE seq + PCM s16le (the audio of that segment)
S→C {"type":"done","metrics":{server_time_to_first_chunk_ms, server_total_ms, audio_ms,
     compute_ms_total, queue_wait_ms_total, rtf, segments, device, streaming_kind}}
C→S {"type":"cancel"} at any time
```

`streaming_kind`: `model_streaming` (the model emits audio incrementally), `segment_streaming`
(text split into sentences, each synthesized fully — Piper and Kokoro), `output_chunked`
(complete audio sent in network chunks).
