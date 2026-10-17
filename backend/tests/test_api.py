import base64
import concurrent.futures
import json

from tests.conftest import download_and_load, make_wav, wait_for

STT = "stt.fake.model"
TTS = "tts.fake.voice"


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["protocol"] == 0
    assert "cpu" in body["system"]


def test_models_listing_and_errors(client):
    models = client.get("/api/models").json()
    assert {m["id"] for m in models} == {STT, TTS}
    assert client.get("/api/models?task=tts").json()[0]["id"] == TTS
    r = client.get("/api/models/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "MODEL_NOT_FOUND"
    assert r.json()["error"]["request_id"] == r.headers["X-Request-ID"]


def test_load_requires_download_and_rejects_gpu(client):
    r = client.post(f"/api/models/{STT}/load", json={"device": "cpu"})
    assert r.json()["error"]["code"] == "MODEL_NOT_DOWNLOADED"
    client.post(f"/api/models/{STT}/download")
    wait_for(lambda: client.get(f"/api/models/{STT}").json()["state"]["download"] == "downloaded")
    r = client.post(f"/api/models/{STT}/load", json={"device": "gpu"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "DEVICE_UNAVAILABLE"


def test_full_lifecycle(client):
    info = download_and_load(client, STT)
    assert info["state"]["load"] == "loaded"
    assert info["state"]["runtime"] == "fake / cpu"
    assert info["state"]["runner"]["max_batch_size"] == 4
    r = client.delete(f"/api/models/{STT}/files")
    assert r.json()["error"]["code"] == "MODEL_BUSY"
    r = client.patch(f"/api/models/{STT}/runner", json={"max_active": 2, "max_wait_ms": 10})
    assert r.json()["state"]["runner"]["max_active"] == 2
    assert client.post(f"/api/models/{STT}/unload").json()["state"]["load"] == "unloaded"
    r = client.delete(f"/api/models/{STT}/files")
    assert r.json()["state"]["download"] == "not_downloaded"


def _transcribe(client, seconds=1.0, model_id=STT):
    return client.post("/api/stt/transcribe",
                       files={"file": ("a.wav", make_wav(seconds), "audio/wav")},
                       data={"options": json.dumps({"model_id": model_id, "language": "en"})})


def test_transcribe_requires_loaded_model(client):
    r = _transcribe(client)
    assert r.status_code == 409 and r.json()["error"]["code"] == "MODEL_NOT_LOADED"


def test_transcribe_and_dynamic_batching(client, stt_adapter):
    download_and_load(client, STT, runner={"max_active": 1, "max_queued": 32,
                                           "max_batch_size": 4, "max_wait_ms": 200})
    r = _transcribe(client, 2.0)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["timings"]["audio_duration_ms"] == 2000
    assert body["timings"]["device"] == "cpu"
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: _transcribe(client, 1.0).json(), range(4)))
    sizes = [r["timings"]["batch_size"] for r in results]
    assert max(sizes) > 1, sizes  # concurrent clients were grouped
    assert any(r["text"].startswith("batched") for r in results)


def test_explicit_batch(client, stt_adapter):
    download_and_load(client, STT)
    files = [("files", (f"f{i}.wav", make_wav(1.0 + i), "audio/wav")) for i in range(3)]
    files.append(("files", ("bad.wav", b"garbage-bytes" * 20, "audio/wav")))
    r = client.post("/api/stt/batch", files=files, data={"options": json.dumps({"model_id": STT})})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["timings"]["batch_size"] == 3
    assert [i["text"] for i in body["items"][:3]] == ["batched 1.0s", "batched 2.0s", "batched 3.0s"]
    assert body["items"][3]["error"]["code"] == "INVALID_AUDIO"
    assert stt_adapter.batches[-1] == 3


def test_tts_synthesize_and_batch_unsupported(client):
    download_and_load(client, TTS)
    r = client.post("/api/tts/synthesize", json={"model_id": TTS, "text": "one two three"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["audio_duration_ms"] == 300
    assert base64.b64decode(body["audio_wav_b64"])[:4] == b"RIFF"
    r = client.post("/api/tts/batch", json={"model_id": TTS, "items": [{"text": "a"}]})
    assert r.json()["error"]["code"] == "MODE_UNSUPPORTED"


def test_errors_reach_event_stream(client):
    download_and_load(client, TTS)
    with client.websocket_connect("/ws/events") as ws:
        assert ws.receive_json()["type"] == "hello"
        r = client.post("/api/tts/synthesize", json={"model_id": TTS, "text": "please FAIL now"})
        assert r.status_code == 500
        rid = r.json()["error"]["request_id"]
        assert r.json()["error"]["code"] == "INFERENCE_FAILED"
        for _ in range(20):
            msg = ws.receive_json()
            if msg["type"] == "log" and msg["data"].get("level") == "error":
                break
        assert msg["data"]["request_id"] == rid
        assert "synthetic engine failure" in msg["data"]["message"]
        assert "Traceback" in msg["data"]["traceback"]


def test_debug_error_route(client):
    r = client.post("/api/debug/error?kind=app")
    assert r.status_code == 500 and r.json()["error"]["code"] == "INFERENCE_FAILED"
    r = client.post("/api/debug/error")
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL"
