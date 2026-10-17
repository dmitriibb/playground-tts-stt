import numpy as np

from common.audio import float_to_pcm16
from tests.conftest import download_and_load

STT = "stt.fake.model"
TTS = "tts.fake.voice"


def _frames(seconds: float, frame_ms: int = 100):
    audio = np.zeros(int(16000 * seconds), dtype=np.float32)
    step = 16 * frame_ms
    for seq, i in enumerate(range(0, len(audio), step)):
        yield seq.to_bytes(4, "little") + float_to_pcm16(audio[i:i + step])


def _collect_until_completed(ws, limit=500):
    msgs = []
    for _ in range(limit):
        msg = ws.receive_json()
        msgs.append(msg)
        if msg["type"] in ("session.completed", "error"):
            break
    return msgs


def test_live_native_session(client):
    download_and_load(client, STT)
    with client.websocket_connect("/ws/stt") as ws:
        ws.send_json({"type": "start", "model_id": STT, "mode": "live_native", "language": "en"})
        ready = ws.receive_json()
        assert ready["type"] == "ready" and ready["protocol"] == 0
        for frame in _frames(2.5):
            ws.send_bytes(frame)
        ws.send_json({"type": "end_input"})
        msgs = _collect_until_completed(ws)
    finals = [m["text"] for m in msgs if m["type"] == "transcript.final"]
    assert finals[:2] == ["one second", "one second"]
    assert finals[-1] == "tail"
    done = msgs[-1]
    assert done["type"] == "session.completed"
    assert done["metrics"]["audio_received_ms"] == 2500


def test_live_windowed_session_commits(client):
    download_and_load(client, STT)
    with client.websocket_connect("/ws/stt") as ws:
        ws.send_json({"type": "start", "model_id": STT, "mode": "live_windowed",
                      "window": {"size_ms": 2000, "stride_ms": 500, "tail_ms": 500}})
        assert ws.receive_json()["type"] == "ready"
        for frame in _frames(5.0):
            ws.send_bytes(frame)
        ws.send_json({"type": "end_input"})
        msgs = _collect_until_completed(ws)
    kinds = {m["type"] for m in msgs}
    assert {"transcript.partial", "transcript.final", "session.completed"} <= kinds
    finals = [m for m in msgs if m["type"] == "transcript.final"]
    # committed segments are contiguous on the stream timeline
    for a, b in zip(finals, finals[1:], strict=False):
        assert a["end_ms"] == b["start_ms"]


def test_live_mode_validation(client):
    download_and_load(client, STT)
    with client.websocket_connect("/ws/stt") as ws:
        ws.send_json({"type": "start", "model_id": STT, "mode": "live_endpointed"})
        err = ws.receive_json()
        assert err["type"] == "error" and err["error"]["code"] == "MODE_UNSUPPORTED"
        ws.send_bytes(b"\x00\x00\x00\x00\x00\x00")
        assert ws.receive_json()["error"]["code"] == "INVALID_REQUEST"


def test_tts_stream(client):
    download_and_load(client, TTS)
    with client.websocket_connect("/ws/tts") as ws:
        ws.send_json({"type": "start", "model_id": TTS,
                      "text": "First sentence is here. Second sentence follows now."})
        meta = ws.receive_json()
        assert meta["type"] == "audio.meta" and meta["streaming_kind"] == "segment_streaming"
        assert meta["segments"] == 2
        chunks = []
        while True:
            msg = ws.receive_json()
            if msg["type"] == "done":
                break
            assert msg["type"] == "segment"
            data = ws.receive_bytes()
            assert int.from_bytes(data[:4], "little") == msg["seq"]
            chunks.append(len(data) - 4)
    assert len(chunks) == 2
    assert msg["metrics"]["segments"] == 2
    assert msg["metrics"]["audio_ms"] == 800
