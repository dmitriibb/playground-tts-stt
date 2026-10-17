"""Model registry: the catalog of known models merged with live state.

Each module (stt, tts) owns one registry with its own catalog and models directory.
The registry handles download, delete, load/unload with device selection, memory
measurement and the per-model ModelRunner.
"""

from __future__ import annotations

import asyncio
import gc
import importlib.util
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from common import downloads
from common.devices import package_version
from common.errors import AppError, ErrorCode, wrap_exception
from common.events import EventPublisher
from common.memory import process_rss_mb, process_vram_mb
from common.runner import ModelRunner
from common.schemas import (
    Device,
    LoadRequest,
    ModelInfo,
    ModelState,
    RunnerConfig,
    RunnerConfigPatch,
    Voice,
)


class Adapter(Protocol):
    """What the registry needs from any engine adapter."""

    def load(self, path: Path, device: Device, threads: int) -> str:
        """Load weights; return a runtime description (e.g. 'onnxruntime 1.24 / Dml')."""
        ...

    def unload(self) -> None: ...


def _cpu_only() -> tuple[list[Device], str | None]:
    return ["cpu"], None


@dataclass
class ModelSpec:
    id: str
    task: str
    name: str
    engine: str
    engine_package: str  # distribution name, for version reporting
    engine_module: str  # importable module, to tell whether the engine is installed
    adapter_factory: Callable[[ModelSpec], Adapter]
    source: downloads.DownloadSource
    languages: list[str]
    modes: dict[str, bool]
    params: str | None = None
    disk_size_mb: float | None = None
    est_ram_mb: float | None = None
    est_vram_mb: float | None = None
    voices: list[Voice] | None = None
    devices_supported: list[Device] = field(default_factory=lambda: ["cpu"])
    devices_now: Callable[[], tuple[list[Device], str | None]] = _cpu_only
    mode_notes: dict[str, str] = field(default_factory=dict)
    streaming_kind: str | None = None
    native_batching: bool = False
    default_runner: RunnerConfig = field(default_factory=RunnerConfig)
    license: str | None = None
    license_note: str | None = None
    notes: str | None = None
    install_hint: str = "uv sync --extra cpu"
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Entry:
    spec: ModelSpec
    path: Path
    download: str = "not_downloaded"
    progress: float = 0.0
    downloaded_mb: float | None = None
    load: str = "unloaded"
    device: Device | None = None
    runtime: str | None = None
    threads: int | None = None
    ram_mb: float | None = None
    vram_mb: float | None = None
    load_time_ms: float | None = None
    error: str | None = None
    adapter: Adapter | None = None
    runner: ModelRunner | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    download_task: asyncio.Task | None = None


RunnerFns = tuple[Callable[[Any], Any], Callable[[list[Any]], list[Any]] | None]


class ModelRegistry:
    def __init__(
        self,
        task: str,
        specs: list[ModelSpec],
        models_dir: Path,
        bus: EventPublisher,
        runner_fns: Callable[[ModelSpec, Adapter], RunnerFns],
    ):
        self.task = task
        self._bus = bus
        self._runner_fns = runner_fns
        self._log = logging.getLogger(f"{task}.registry")
        self._entries: dict[str, _Entry] = {}
        for spec in specs:
            path = (models_dir / spec.id).resolve()
            entry = _Entry(spec=spec, path=path)
            if downloads.is_downloaded(path):
                entry.download, entry.progress = "downloaded", 1.0
                entry.downloaded_mb = round(downloads.dir_size_mb(path), 1)
            self._entries[spec.id] = entry

    # ---- queries ---------------------------------------------------------------------

    def ids(self) -> list[str]:
        return list(self._entries)

    def has(self, model_id: str) -> bool:
        return model_id in self._entries

    def list_models(self) -> list[ModelInfo]:
        return [self._info(e) for e in self._entries.values()]

    def info(self, model_id: str) -> ModelInfo:
        return self._info(self._entry(model_id))

    def spec(self, model_id: str) -> ModelSpec:
        return self._entry(model_id).spec

    def loaded(self, model_id: str) -> tuple[ModelSpec, Any, ModelRunner, Device]:
        """Spec, adapter, runner and device of a loaded model, or MODEL_NOT_LOADED."""
        entry = self._entry(model_id)
        if entry.load != "loaded" or entry.adapter is None or entry.runner is None:
            raise AppError(ErrorCode.MODEL_NOT_LOADED, f"Model {model_id} is not loaded",
                           {"model_id": model_id})
        assert entry.device is not None
        return entry.spec, entry.adapter, entry.runner, entry.device

    def _entry(self, model_id: str) -> _Entry:
        try:
            return self._entries[model_id]
        except KeyError:
            raise AppError(ErrorCode.MODEL_NOT_FOUND, f"Unknown model {model_id}",
                           {"model_id": model_id}) from None

    def _engine_available(self, spec: ModelSpec) -> bool:
        return importlib.util.find_spec(spec.engine_module) is not None

    def _info(self, e: _Entry) -> ModelInfo:
        s = e.spec
        engine_ok = self._engine_available(s)
        devices_now, device_reason = s.devices_now() if engine_ok else ([], None)
        devices_now = [d for d in devices_now if d in s.devices_supported]
        if "gpu" not in s.devices_supported:
            device_reason = device_reason or f"{s.engine} has no GPU path on this platform"
        return ModelInfo(
            id=s.id, task=s.task, name=s.name, engine=s.engine,
            engine_version=package_version(s.engine_package),
            source=s.source.describe(), params=s.params, disk_size_mb=s.disk_size_mb,
            est_ram_mb=s.est_ram_mb, est_vram_mb=s.est_vram_mb, languages=s.languages,
            voices=s.voices, devices_supported=s.devices_supported,
            devices_available_now=devices_now,
            device_unavailable_reason=None if "gpu" in devices_now else device_reason,
            modes=s.modes, mode_notes=s.mode_notes, streaming_kind=s.streaming_kind,
            native_batching=s.native_batching, license=s.license, license_note=s.license_note,
            notes=s.notes, engine_available=engine_ok,
            unavailable_reason=None if engine_ok else
            f"Engine package '{s.engine_package}' is not installed ({s.install_hint})",
            state=ModelState(
                download=e.download, download_progress=e.progress, downloaded_mb=e.downloaded_mb,
                path=str(e.path), load=e.load, device=e.device, runtime=e.runtime,
                threads=e.threads, ram_mb=e.ram_mb, vram_mb=e.vram_mb,
                load_time_ms=e.load_time_ms,
                runner=e.runner.state() if e.runner else None, error=e.error,
            ),
        )

    def _publish(self, e: _Entry) -> None:
        self._bus.publish("model.state", self.task, {"model": self._info(e).model_dump()})

    # ---- download / delete -----------------------------------------------------------

    def start_download(self, model_id: str) -> ModelInfo:
        e = self._entry(model_id)
        if e.download == "downloading":
            return self._info(e)
        if e.download == "downloaded":
            raise AppError(ErrorCode.INVALID_REQUEST, f"{model_id} is already downloaded")
        e.download, e.progress, e.error = "downloading", 0.0, None
        e.download_task = asyncio.create_task(self._download(e))
        self._publish(e)
        return self._info(e)

    async def _download(self, e: _Entry) -> None:
        loop = asyncio.get_running_loop()
        last = [0.0]
        expected = e.spec.disk_size_mb or 0

        def progress(done_mb: float, total_mb: float) -> None:
            now = time.monotonic()
            if now - last[0] < 0.25:
                return
            last[0] = now
            total = total_mb or expected
            e.progress = min(0.99, done_mb / total) if total else 0.0
            e.downloaded_mb = round(done_mb, 1)
            self._bus.publish("download.progress", self.task, {
                "model_id": e.spec.id, "progress": e.progress,
                "downloaded_mb": e.downloaded_mb, "total_mb": round(total, 1) if total else None,
            })

        try:
            await loop.run_in_executor(None, downloads.download, e.spec.source, e.path, progress)
            e.download, e.progress = "downloaded", 1.0
            e.downloaded_mb = round(downloads.dir_size_mb(e.path), 1)
            self._log.info("Downloaded %s to %s", e.spec.id, e.path)
        except Exception as exc:
            e.download, e.error = "error", f"Download failed: {exc}"
            self._log.error("Download of %s failed: %s", e.spec.id, exc, exc_info=True,
                            extra={"code": ErrorCode.DOWNLOAD_FAILED.value, "model_id": e.spec.id})
        finally:
            e.download_task = None
            self._publish(e)

    async def delete_files(self, model_id: str) -> ModelInfo:
        e = self._entry(model_id)
        async with e.lock:
            if e.load in ("loaded", "loading", "unloading"):
                raise AppError(ErrorCode.MODEL_BUSY, f"Unload {model_id} before deleting its files")
            if e.download == "downloading":
                raise AppError(ErrorCode.MODEL_BUSY, f"{model_id} is downloading")
            await asyncio.to_thread(downloads.delete_files, e.path)
            e.download, e.progress, e.downloaded_mb, e.error = "not_downloaded", 0.0, None, None
            self._log.info("Deleted files of %s (%s)", model_id, e.path)
        self._publish(e)
        return self._info(e)

    # ---- load / unload ---------------------------------------------------------------

    async def load(self, model_id: str, req: LoadRequest) -> ModelInfo:
        e = self._entry(model_id)
        s = e.spec
        async with e.lock:
            if e.load == "loaded":
                raise AppError(ErrorCode.MODEL_BUSY,
                               f"{model_id} is already loaded on {e.device}; unload it first")
            if not self._engine_available(s):
                raise AppError(ErrorCode.ENGINE_UNAVAILABLE, self._info(e).unavailable_reason or "")
            if e.download != "downloaded":
                raise AppError(ErrorCode.MODEL_NOT_DOWNLOADED, f"Download {model_id} first")
            devices_now, reason = s.devices_now()
            if req.device not in s.devices_supported or req.device not in devices_now:
                raise AppError(ErrorCode.DEVICE_UNAVAILABLE,
                               reason or f"{s.engine} does not support {req.device} here",
                               {"model_id": model_id, "device": req.device})
            e.load, e.error, e.device = "loading", None, req.device
            self._publish(e)
            gc.collect()
            ram_before, vram_before = process_rss_mb(), process_vram_mb()
            started = time.perf_counter()
            adapter = s.adapter_factory(s)
            try:
                runtime = await asyncio.to_thread(adapter.load, e.path, req.device, req.threads)
            except Exception as exc:
                err = wrap_exception(exc, ErrorCode.INTERNAL)
                e.load, e.device, e.error = "error", None, f"Load failed: {err.message}"
                self._log.error("Loading %s on %s failed: %s", model_id, req.device, err.message,
                                exc_info=not isinstance(exc, AppError),
                                extra={"code": err.code.value, "model_id": model_id})
                err.logged = True
                self._publish(e)
                raise err from exc
            e.load_time_ms = (time.perf_counter() - started) * 1000
            ram_after, vram_after = process_rss_mb(), process_vram_mb()
            e.ram_mb = round(max(0.0, ram_after - ram_before), 1)
            e.vram_mb = (round(max(0.0, vram_after - vram_before), 1)
                         if vram_after is not None and vram_before is not None and req.device == "gpu"
                         else None)
            run_one, run_batch = self._runner_fns(s, adapter)
            config = req.runner or s.default_runner
            runner = ModelRunner(
                model_id=model_id, config=config, run_one=run_one,
                run_batch=run_batch if s.native_batching else None,
                on_change=lambda: self._publish(e), log_source=self.task,
            )
            runner.start()
            e.adapter, e.runner, e.runtime, e.threads = adapter, runner, runtime, req.threads
            e.load = "loaded"
            self._log.info("Loaded %s on %s (%s) in %.0f ms", model_id, req.device, runtime,
                           e.load_time_ms)
        self._publish(e)
        return self._info(e)

    async def unload(self, model_id: str) -> ModelInfo:
        e = self._entry(model_id)
        async with e.lock:
            if e.load not in ("loaded", "error"):
                raise AppError(ErrorCode.MODEL_NOT_LOADED, f"{model_id} is not loaded")
            e.load = "unloading"
            self._publish(e)
            try:
                if e.runner:
                    await e.runner.stop()
                if e.adapter:
                    await asyncio.to_thread(e.adapter.unload)
            finally:
                e.adapter = e.runner = None
                e.load, e.device, e.runtime, e.threads = "unloaded", None, None, None
                e.ram_mb = e.vram_mb = e.load_time_ms = None
                e.error = None
                gc.collect()
        self._publish(e)
        return self._info(e)

    def patch_runner(self, model_id: str, patch: RunnerConfigPatch) -> ModelInfo:
        e = self._entry(model_id)
        if e.runner is None:
            raise AppError(ErrorCode.MODEL_NOT_LOADED, f"{model_id} is not loaded")
        e.runner.reconfigure(patch)
        self._publish(e)
        return self._info(e)

    async def shutdown(self) -> None:
        for model_id, e in self._entries.items():
            if e.load == "loaded":
                try:
                    await self.unload(model_id)
                except Exception:
                    self._log.exception("Unload of %s failed during shutdown", model_id)
