from __future__ import annotations

import io
import time
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from common.events import EventBus
from gateway.app import create_app
from gateway.config import Settings
from stt.service import LocalSttService
from tests.fakes import FakeSttAdapter, stt_spec, tts_spec
from tts.service import LocalTtsService


def make_wav(seconds: float, sr: int = 16000) -> bytes:
    t = np.arange(int(seconds * sr)) / sr
    pcm = (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


@pytest.fixture
def stt_adapter() -> FakeSttAdapter:
    return FakeSttAdapter(delay_s=0.02)


@pytest.fixture
def client(tmp_path, stt_adapter):
    bus = EventBus()
    settings = Settings(models_dir=tmp_path / "models", fixtures_dir=tmp_path / "fixtures",
                        cors_origins="http://localhost:5173", _env_file=None)
    stt = LocalSttService(tmp_path / "models" / "stt", bus, specs=[stt_spec(stt_adapter)])
    tts = LocalTtsService(tmp_path / "models" / "tts", bus, specs=[tts_spec()])
    app = create_app(settings, stt=stt, tts=tts, bus=bus)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def wait_for(predicate, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


def download_and_load(client: TestClient, model_id: str, **load_body) -> dict:
    assert client.post(f"/api/models/{model_id}/download").status_code == 202
    wait_for(lambda: client.get(f"/api/models/{model_id}").json()["state"]["download"] == "downloaded")
    r = client.post(f"/api/models/{model_id}/load", json={"device": "cpu", **load_body})
    assert r.status_code == 200, r.text
    return r.json()
