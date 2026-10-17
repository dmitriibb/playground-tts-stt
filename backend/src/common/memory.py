"""Process memory measurement: RAM via psutil, dedicated VRAM via Windows PDH.

The PDH counter `\\GPU Process Memory(pid_<pid>_*)\\Dedicated Usage` is vendor
neutral: it sees allocations made through DirectML, Vulkan and ROCm/HIP alike.
Values are approximate and are labelled as such in the UI.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading

import psutil

log = logging.getLogger("common.memory")

_PROCESS = psutil.Process(os.getpid())


def process_rss_mb() -> float:
    return _PROCESS.memory_info().rss / (1024 * 1024)


class _PdhGpuMemory:
    PDH_FMT_LARGE = 0x00000400
    PDH_MORE_DATA = 0x800007D2

    class _Value(ctypes.Structure):
        _fields_ = [("CStatus", ctypes.c_ulong), ("largeValue", ctypes.c_longlong)]

    class _Item(ctypes.Structure):
        pass

    _Item._fields_ = [("szName", ctypes.c_wchar_p), ("FmtValue", _Value)]

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._query = ctypes.c_void_p()
        self._counter = ctypes.c_void_p()
        self._ok = False
        self._prefix = f"pid_{os.getpid()}_"
        try:
            self._pdh = ctypes.WinDLL("pdh.dll")
            if self._pdh.PdhOpenQueryW(None, None, ctypes.byref(self._query)) != 0:
                return
            path = r"\GPU Process Memory(*)\Dedicated Usage"
            status = self._pdh.PdhAddEnglishCounterW(
                self._query, ctypes.c_wchar_p(path), None, ctypes.byref(self._counter)
            )
            self._ok = status == 0
        except Exception as exc:  # pragma: no cover - platform specific
            log.debug("PDH unavailable: %s", exc)

    def dedicated_mb(self) -> float | None:
        if not self._ok:
            return None
        with self._lock:
            pdh = self._pdh
            if pdh.PdhCollectQueryData(self._query) != 0:
                return None
            size = ctypes.c_ulong(0)
            count = ctypes.c_ulong(0)
            status = pdh.PdhGetFormattedCounterArrayW(
                self._counter, self.PDH_FMT_LARGE, ctypes.byref(size), ctypes.byref(count), None
            )
            if status & 0xFFFFFFFF != self.PDH_MORE_DATA or size.value == 0:
                return 0.0 if status == 0 else None
            buffer = (ctypes.c_byte * size.value)()
            status = pdh.PdhGetFormattedCounterArrayW(
                self._counter, self.PDH_FMT_LARGE, ctypes.byref(size), ctypes.byref(count), buffer
            )
            if status != 0:
                return None
            items = ctypes.cast(buffer, ctypes.POINTER(self._Item))
            total = 0
            for i in range(count.value):
                item = items[i]
                if item.szName and item.szName.startswith(self._prefix):
                    total += item.FmtValue.largeValue
            return total / (1024 * 1024)


_gpu_probe: _PdhGpuMemory | None = None
_gpu_probe_lock = threading.Lock()


def process_vram_mb() -> float | None:
    """Dedicated GPU memory used by this process (MB), or None when not measurable."""
    global _gpu_probe
    if sys.platform != "win32":
        return None
    with _gpu_probe_lock:
        if _gpu_probe is None:
            _gpu_probe = _PdhGpuMemory()
    try:
        return _gpu_probe.dedicated_mb()
    except Exception as exc:  # pragma: no cover
        log.debug("VRAM query failed: %s", exc)
        return None
