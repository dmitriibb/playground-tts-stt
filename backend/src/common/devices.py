"""Hardware and runtime detection (CPU, GPU names, ONNX Runtime / CTranslate2 / torch)."""

from __future__ import annotations

import importlib.metadata
import json
import logging
import os
import platform
import subprocess
import sys
from functools import lru_cache
from typing import Any

import psutil

log = logging.getLogger("common.devices")

# ONNX Runtime GPU providers in order of preference. DirectML is the vendor-neutral
# Windows path; ROCm/MIGraphX are the Linux AMD paths.
ORT_GPU_PROVIDERS = (
    "ROCMExecutionProvider",
    "MIGraphXExecutionProvider",
    "CUDAExecutionProvider",
    "DmlExecutionProvider",
)


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


@lru_cache(maxsize=1)
def gpu_names() -> list[str]:
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name | ConvertTo-Json"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            if not out:
                return []
            names = json.loads(out)
            return [names] if isinstance(names, str) else list(names)
        if sys.platform.startswith("linux"):
            out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5).stdout
            return [line.split(": ", 1)[1] for line in out.splitlines()
                    if "VGA" in line or "Display" in line or "3D controller" in line]
    except Exception as exc:
        log.debug("GPU name detection failed: %s", exc)
    return []


@lru_cache(maxsize=1)
def onnxruntime_info() -> dict[str, Any] | None:
    try:
        import onnxruntime as ort
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    providers = ort.get_available_providers()
    distribution = next(
        (d for d in ("onnxruntime-directml", "onnxruntime-rocm", "onnxruntime-gpu", "onnxruntime")
         if package_version(d)),
        None,
    )
    return {
        "available": True,
        "version": ort.__version__,
        "distribution": distribution,
        "providers": providers,
        "gpu_provider": ort_gpu_provider(),
    }


def ort_gpu_provider() -> str | None:
    try:
        import onnxruntime as ort
    except Exception:
        return None
    available = set(ort.get_available_providers())
    return next((p for p in ORT_GPU_PROVIDERS if p in available), None)


@lru_cache(maxsize=1)
def ctranslate2_info() -> dict[str, Any] | None:
    version = package_version("ctranslate2")
    if version is None:
        return None
    try:
        import ctranslate2

        cuda = ctranslate2.get_cuda_device_count()
    except Exception as exc:
        return {"version": version, "error": str(exc)}
    return {"version": version, "cuda_devices": cuda}


@lru_cache(maxsize=1)
def torch_info() -> dict[str, Any] | None:
    """Only reports torch if it is installed. Importing torch is slow, so call this lazily."""
    if package_version("torch") is None:
        return None
    try:
        import torch

        info: dict[str, Any] = {
            "version": torch.__version__,
            "hip": getattr(torch.version, "hip", None),
            "cuda": getattr(torch.version, "cuda", None),
            "gpu_available": bool(torch.cuda.is_available()),
        }
        if info["gpu_available"]:
            info["device_name"] = torch.cuda.get_device_name(0)
        return info
    except Exception as exc:
        return {"error": str(exc)}


@lru_cache(maxsize=1)
def cpu_info() -> dict[str, Any]:
    name = platform.processor()
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            name = out or name
        except Exception:
            pass
    return {
        "name": name,
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "ram_total_mb": round(psutil.virtual_memory().total / (1024 * 1024)),
    }


def system_info() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "pid": os.getpid(),
        "cpu": cpu_info(),
        "gpus": gpu_names(),
        "runtimes": {
            "onnxruntime": onnxruntime_info(),
            "ctranslate2": ctranslate2_info(),
            "torch": torch_info(),
        },
    }
