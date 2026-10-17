import numpy as np
import pytest

from common.audio import decode_audio, encode_wav, float_to_pcm16, pcm16_to_float, resample
from common.errors import AppError, ErrorCode
from tests.conftest import make_wav
from tts.service import split_segments


def test_wav_roundtrip_and_resample():
    data = make_wav(1.0, sr=48000)
    audio = decode_audio(data, 16000)
    assert abs(len(audio) - 16000) <= 2
    assert audio.dtype == np.float32
    assert 0.25 < np.abs(audio).max() < 0.35


def test_pcm16_conversion():
    x = np.array([0.0, 0.5, -0.5, 1.0, -1.0], dtype=np.float32)
    back = pcm16_to_float(float_to_pcm16(x))
    assert np.allclose(back, x, atol=1e-4)


def test_odd_pcm_is_invalid():
    with pytest.raises(AppError) as exc:
        pcm16_to_float(b"\x00\x01\x02")
    assert exc.value.code == ErrorCode.INVALID_AUDIO


def test_garbage_is_invalid_audio():
    with pytest.raises(AppError) as exc:
        decode_audio(b"definitely not audio" * 10)
    assert exc.value.code == ErrorCode.INVALID_AUDIO


def test_encode_wav_header():
    wav = encode_wav(np.zeros(1600, dtype=np.float32), 16000)
    assert wav[:4] == b"RIFF" and len(wav) == 44 + 3200
    assert len(resample(np.zeros(16000, dtype=np.float32), 16000, 8000)) == 8000


def test_split_segments():
    text = "Hello there. This is a test of the splitter! Ok. And the last sentence is here?"
    parts = split_segments(text)
    assert parts == ["Hello there. This is a test of the splitter!",
                     "Ok. And the last sentence is here?"]
    assert split_segments("short") == ["short"]
