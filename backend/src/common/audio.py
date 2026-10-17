"""Audio helpers: decode any container to float32 mono, resample, PCM16 and WAV conversion."""

from __future__ import annotations

import io
import wave

import numpy as np
import soxr

from common.errors import AppError, ErrorCode


def decode_audio(data: bytes, target_sr: int = 16000) -> np.ndarray:
    """Decode WAV/MP3/OGG/WebM/FLAC/... bytes to float32 mono at `target_sr`."""
    if not data:
        raise AppError(ErrorCode.INVALID_AUDIO, "Empty audio payload")
    # Fast path for plain 16-bit PCM WAV (what the browser recorder uploads).
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        try:
            audio, sr = read_wav(data)
            return resample(audio, sr, target_sr)
        except (wave.Error, ValueError):
            pass  # e.g. float WAV: fall back to PyAV
    try:
        import av

        chunks: list[np.ndarray] = []
        with av.open(io.BytesIO(data)) as container:
            if not container.streams.audio:
                raise AppError(ErrorCode.INVALID_AUDIO, "No audio stream in file")
            resampler = av.AudioResampler(format="flt", layout="mono", rate=target_sr)
            for frame in container.decode(audio=0):
                for out in resampler.resample(frame):
                    chunks.append(out.to_ndarray().reshape(-1))
            for out in resampler.resample(None):
                chunks.append(out.to_ndarray().reshape(-1))
    except AppError:
        raise
    except Exception as exc:
        raise AppError(ErrorCode.INVALID_AUDIO, f"Cannot decode audio: {exc}") from exc
    if not chunks:
        raise AppError(ErrorCode.INVALID_AUDIO, "Audio has no samples")
    return np.concatenate(chunks).astype(np.float32, copy=False)


def read_wav(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise ValueError("only 16-bit PCM handled here")
        sr = wf.getframerate()
        channels = wf.getnchannels()
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2")
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    return pcm.astype(np.float32) / 32768.0, sr


def resample(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr:
        return audio.astype(np.float32, copy=False)
    return soxr.resample(audio, src_sr, dst_sr).astype(np.float32, copy=False)


def pcm16_to_float(data: bytes) -> np.ndarray:
    if len(data) % 2:
        raise AppError(ErrorCode.INVALID_AUDIO, "PCM16 payload has an odd number of bytes")
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(audio: np.ndarray) -> bytes:
    clipped = np.clip(audio, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def encode_wav(audio: np.ndarray | bytes, sample_rate: int) -> bytes:
    pcm = audio if isinstance(audio, bytes) else float_to_pcm16(audio)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def duration_ms(num_samples: int, sample_rate: int) -> float:
    return 1000.0 * num_samples / sample_rate if sample_rate else 0.0
