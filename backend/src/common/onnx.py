"""ONNX Runtime session creation with explicit device selection (no silent fallback)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from common.devices import ort_gpu_provider
from common.errors import AppError, ErrorCode


def ort_devices() -> tuple[list[str], str | None]:
    """Devices ONNX Runtime can use now, and the reason GPU is unavailable (if it is)."""
    provider = ort_gpu_provider()
    if provider:
        return ["cpu", "gpu"], None
    return ["cpu"], "No GPU execution provider in this onnxruntime build (install onnxruntime-directml)"


def create_session(model: str | Path | bytes, device: str, threads: int = 0) -> tuple[Any, str]:
    """Return (InferenceSession, runtime description). Raises DEVICE_UNAVAILABLE for a GPU
    request that onnxruntime cannot satisfy instead of quietly running on CPU."""
    import onnxruntime as ort

    options = ort.SessionOptions()
    if threads > 0:
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
    if device == "gpu":
        provider = ort_gpu_provider()
        if provider is None:
            raise AppError(ErrorCode.DEVICE_UNAVAILABLE, ort_devices()[1] or "GPU unavailable")
        if provider == "DmlExecutionProvider":
            # DirectML does not support memory patterns or parallel execution.
            options.enable_mem_pattern = False
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        providers = [provider, "CPUExecutionProvider"]
    else:
        provider = "CPUExecutionProvider"
        providers = [provider]
    source = model if isinstance(model, bytes) else str(model)
    session = ort.InferenceSession(source, sess_options=options, providers=providers)
    if provider not in session.get_providers():
        raise AppError(
            ErrorCode.DEVICE_UNAVAILABLE,
            f"{provider} could not be initialised (session providers: {session.get_providers()})",
        )
    runtime = f"onnxruntime {ort.__version__} / {provider.removesuffix('ExecutionProvider')}"
    return session, runtime
