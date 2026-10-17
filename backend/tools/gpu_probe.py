"""Phase 0 GPU spike: which GPU paths work on this machine?

Run on the target machine (RX 9070 XT) after installing the optional GPU packages:
    .venv/Scripts/python tools/gpu_probe.py [--onnx path/to/model.onnx] [--whisper-cli path]

Prints one line per path (OK / FAIL / SKIP + reason) and a JSON summary at the end.
Copy the results into docs/COMPATIBILITY.md.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from common.devices import gpu_names, onnxruntime_info, ort_gpu_provider, package_version  # noqa: E402
from common.memory import process_vram_mb  # noqa: E402

results: dict[str, dict] = {}


def report(name: str, status: str, detail: str, **extra) -> None:
    results[name] = {"status": status, "detail": detail, **extra}
    print(f"[{status:4}] {name:28} {detail}")


def probe_torch() -> None:
    if package_version("torch") is None:
        return report("torch (ROCm/HIP)", "SKIP", "torch not installed (install the AMD ROCm Windows wheel)")
    try:
        import torch

        hip = getattr(torch.version, "hip", None)
        if not torch.cuda.is_available():
            return report("torch (ROCm/HIP)", "FAIL", f"torch {torch.__version__}, hip={hip}: no GPU visible")
        dev = torch.cuda.get_device_name(0)
        a = torch.randn(4096, 4096, device="cuda", dtype=torch.float16)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(10):
            a @ a
        torch.cuda.synchronize()
        tflops = 10 * 2 * 4096**3 / (time.perf_counter() - t0) / 1e12
        free, total = torch.cuda.mem_get_info()
        report("torch (ROCm/HIP)", "OK",
               f"{dev}, torch {torch.__version__}, hip {hip}, fp16 matmul {tflops:.1f} TFLOPS",
               vram_free_mb=free // 2**20, vram_total_mb=total // 2**20)
    except Exception as exc:
        report("torch (ROCm/HIP)", "FAIL", f"{type(exc).__name__}: {exc}")


def find_onnx(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    root = Path(__file__).resolve().parents[1] / "models"
    for pattern in ("**/silero_vad.onnx", "**/*.onnx"):
        found = next(root.glob(pattern), None)
        if found:
            return found
    return None


def probe_onnxruntime(model: Path | None) -> None:
    info = onnxruntime_info() or {}
    provider = ort_gpu_provider()
    if not info.get("available"):
        return report("onnxruntime GPU", "FAIL", f"onnxruntime not importable: {info.get('error')}")
    if provider is None:
        return report("onnxruntime GPU", "FAIL", f"{info.get('distribution')}: providers {info.get('providers')}")
    if model is None:
        return report("onnxruntime GPU", "SKIP", f"{provider} present; no .onnx model to run (download Silero VAD)")
    try:
        import numpy as np
        import onnxruntime as ort

        from common.onnx import create_session

        before = process_vram_mb()
        session, runtime = create_session(model, "gpu")
        feeds = {}
        for inp in session.get_inputs():
            shape = [d if isinstance(d, int) else 1 for d in inp.shape]
            if inp.name == "input" and model.name == "silero_vad.onnx":
                shape = [1, 576]
            dtype = {"tensor(float)": np.float32, "tensor(int64)": np.int64}.get(inp.type, np.float32)
            feeds[inp.name] = (np.array(16000, dtype=np.int64) if inp.name == "sr"
                               else np.zeros(shape, dtype=dtype))
        session.run(None, feeds)
        after = process_vram_mb()
        report("onnxruntime GPU", "OK", f"{runtime} ran {model.name}", ort=ort.__version__,
               vram_delta_mb=None if before is None or after is None else round(after - before, 1))
    except Exception as exc:
        report("onnxruntime GPU", "FAIL", f"{type(exc).__name__}: {exc}")


def probe_whisper_cpp(cli: str | None) -> None:
    exe = cli or shutil.which("whisper-cli") or shutil.which("whisper-cli.exe")
    if package_version("pywhispercpp"):
        report("pywhispercpp", "OK", f"installed {package_version('pywhispercpp')} (check it was built with Vulkan)")
    if not exe:
        return report("whisper.cpp (Vulkan)", "SKIP",
                      "whisper-cli not found: download the Vulkan release build or pass --whisper-cli")
    try:
        out = subprocess.run([exe, "--help"], capture_output=True, text=True, timeout=30)
        text = (out.stdout + out.stderr).lower()
        vulkan = "vulkan" in text
        report("whisper.cpp (Vulkan)", "OK" if vulkan else "FAIL",
               f"{exe}: {'Vulkan backend mentioned' if vulkan else 'no Vulkan in --help output'}"
               " (run it on a fixture to confirm it uses the GPU)")
    except Exception as exc:
        report("whisper.cpp (Vulkan)", "FAIL", f"{type(exc).__name__}: {exc}")


def probe_pdh() -> None:
    value = process_vram_mb()
    if value is None:
        report("PDH GPU memory counter", "FAIL", "\\GPU Process Memory counter not readable")
    else:
        report("PDH GPU memory counter", "OK", f"this process uses {value:.1f} MB dedicated VRAM now")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--onnx", help="ONNX model to run on the GPU provider")
    parser.add_argument("--whisper-cli", help="Path to a whisper.cpp whisper-cli binary")
    args = parser.parse_args()
    print(f"GPUs: {gpu_names() or 'none detected'}\n")
    probe_pdh()
    probe_onnxruntime(find_onnx(args.onnx))
    probe_torch()
    probe_whisper_cpp(args.whisper_cli)
    probe_pdh()
    print("\n" + json.dumps({"gpus": gpu_names(), "results": results}, indent=2))


if __name__ == "__main__":
    main()
