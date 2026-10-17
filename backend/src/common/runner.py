"""ModelRunner: per-model scheduling.

- a bounded wait queue (`max_queued`); a full queue rejects with QUEUE_FULL
- `max_active` consumers, each running jobs on its own worker thread
- an optional dynamic batch collector (`max_batch_size`, `max_wait_ms`) used only
  when the engine has real native batching (`run_batch` is given)

Every result comes with timings: queue wait, compute time, batch id and size.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from collections.abc import Callable, Hashable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from common.errors import AppError, ErrorCode, wrap_exception
from common.schemas import RunnerConfig, RunnerConfigPatch, RunnerState

log = logging.getLogger("common.runner")

_batch_ids = itertools.count(1)


@dataclass
class JobTimings:
    queue_wait_ms: float
    compute_ms: float
    batch_id: int
    batch_size: int


@dataclass
class _Job:
    payload: Any
    future: asyncio.Future
    enqueued: float
    batch_key: Hashable | None
    request_id: str | None = None
    fn: Callable[[Any], Any] | None = None


@dataclass
class _Counters:
    active: int = 0
    completed: int = 0
    failed: int = 0
    rejected: int = 0
    batches: int = 0


@dataclass
class ModelRunner:
    model_id: str
    config: RunnerConfig
    run_one: Callable[[Any], Any]
    run_batch: Callable[[list[Any]], list[Any]] | None = None
    on_change: Callable[[], None] | None = None
    log_source: str = "common"

    _queue: asyncio.Queue[_Job] = field(init=False)
    _consumers: list[asyncio.Task] = field(init=False, default_factory=list)
    _executor: ThreadPoolExecutor | None = field(init=False, default=None)
    _generation: int = field(init=False, default=0)
    _counters: _Counters = field(init=False, default_factory=_Counters)
    _stopped: bool = field(init=False, default=False)
    _notify_handle: asyncio.TimerHandle | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._queue = asyncio.Queue()
        self._log = logging.getLogger(f"{self.log_source}.runner")
        if self.run_batch is None:
            self.config = self.config.model_copy(update={"max_batch_size": 1, "max_wait_ms": 0})

    # ---- lifecycle -------------------------------------------------------------------

    def start(self) -> None:
        self._spawn_consumers()

    async def stop(self) -> None:
        """Reject queued jobs, then wait for running ones (the model must not be freed
        while a worker thread still uses it)."""
        self._stopped = True
        for task in self._consumers:
            task.cancel()
        while not self._queue.empty():
            job = self._queue.get_nowait()
            if not job.future.done():
                job.future.set_exception(AppError(ErrorCode.CANCELLED, "Model is being unloaded"))
        if self._executor is not None:
            await asyncio.to_thread(self._executor.shutdown, True)
        self._consumers.clear()

    def _spawn_consumers(self) -> None:
        self._generation += 1
        old_executor = self._executor
        self._executor = ThreadPoolExecutor(
            max_workers=self.config.max_active, thread_name_prefix=f"run-{self.model_id}"
        )
        self._consumers = [
            asyncio.create_task(self._consume(self._generation), name=f"runner-{self.model_id}-{i}")
            for i in range(self.config.max_active)
        ]
        if old_executor is not None:
            old_executor.shutdown(wait=False)

    # ---- public API ------------------------------------------------------------------

    @property
    def supports_batching(self) -> bool:
        return self.run_batch is not None

    def state(self) -> RunnerState:
        c = self._counters
        return RunnerState(
            **self.config.model_dump(),
            active=c.active, queued=self._queue.qsize(), completed=c.completed,
            failed=c.failed, rejected=c.rejected, batches=c.batches,
        )

    def reconfigure(self, patch: RunnerConfigPatch) -> None:
        update = patch.model_dump(exclude_none=True)
        if self.run_batch is None:
            update.pop("max_batch_size", None)
            update.pop("max_wait_ms", None)
        old_active = self.config.max_active
        self.config = self.config.model_copy(update=update)
        if self.config.max_active != old_active and not self._stopped:
            # Old consumers finish their current job, hand back anything they pulled
            # afterwards and exit (generation check in _consume).
            self._spawn_consumers()
        self._notify()

    async def submit(
        self,
        payload: Any,
        *,
        batch_key: Hashable | None = None,
        request_id: str | None = None,
        fn: Callable[[Any], Any] | None = None,
    ) -> tuple[Any, JobTimings]:
        """Queue one job and wait for its result.

        `batch_key=None` means the job never joins a batch. Jobs with equal keys may be
        batched together. `fn` overrides `run_one` for this job (e.g. a streaming step)."""
        if self._stopped:
            raise AppError(ErrorCode.MODEL_NOT_LOADED, f"Model {self.model_id} is unloading")
        if self._queue.qsize() >= self.config.max_queued and self._idle_slots() == 0:
            self._counters.rejected += 1
            self._notify()
            raise AppError(
                ErrorCode.QUEUE_FULL,
                f"Queue of {self.model_id} is full ({self.config.max_queued} waiting)",
                {"model_id": self.model_id, "max_queued": self.config.max_queued},
            )
        loop = asyncio.get_running_loop()
        job = _Job(payload, loop.create_future(), time.perf_counter(),
                   batch_key if self.run_batch else None, request_id, fn)
        self._queue.put_nowait(job)
        self._notify()
        return await job.future

    # ---- internals -------------------------------------------------------------------

    def _idle_slots(self) -> int:
        return max(0, self.config.max_active - self._counters.active)

    async def _consume(self, generation: int) -> None:
        executor = self._executor
        carry: _Job | None = None
        while not self._stopped:
            job = carry or await self._queue.get()
            carry = None
            if job.future.done():  # caller went away while waiting
                continue
            batch = [job]
            if job.batch_key is not None and self.config.max_batch_size > 1:
                carry = await self._collect(batch)
            batch = [j for j in batch if not j.future.done()]
            if generation != self._generation:  # reconfigured: newer consumers take over
                for j in [*batch, *([carry] if carry else [])]:
                    self._queue.put_nowait(j)
                return
            if batch:
                await self._execute(batch, executor)
        if carry is not None:
            self._queue.put_nowait(carry)

    async def _collect(self, batch: list[_Job]) -> _Job | None:
        """Fill `batch` with compatible jobs until it is full or `max_wait_ms` passes.
        Returns a pulled job that cannot join this batch (runs next)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.config.max_wait_ms / 1000
        key = batch[0].batch_key
        while len(batch) < self.config.max_batch_size:
            remaining = deadline - loop.time()
            try:
                if remaining <= 0:
                    nxt = self._queue.get_nowait()
                else:
                    nxt = await asyncio.wait_for(self._queue.get(), remaining)
            except (asyncio.QueueEmpty, TimeoutError):
                break
            if nxt.future.done():
                continue
            if nxt.batch_key != key:
                return nxt
            batch.append(nxt)
        return None

    async def _execute(self, batch: list[_Job], executor: ThreadPoolExecutor | None) -> None:
        loop = asyncio.get_running_loop()
        batch_id = next(_batch_ids)
        started = time.perf_counter()
        self._counters.active += len(batch)
        self._counters.batches += 1
        self._notify()
        try:
            if len(batch) == 1:
                job = batch[0]
                fn = job.fn or self.run_one
                results = [await loop.run_in_executor(executor, fn, job.payload)]
            else:
                assert self.run_batch is not None
                results = await loop.run_in_executor(
                    executor, self.run_batch, [j.payload for j in batch]
                )
        except asyncio.CancelledError:
            for job in batch:
                if not job.future.done():
                    job.future.set_exception(AppError(ErrorCode.CANCELLED, "Runner stopped"))
            raise
        except BaseException as exc:  # engine failure for the whole batch
            results = [exc] * len(batch)
        finally:
            self._counters.active -= len(batch)
        compute_ms = (time.perf_counter() - started) * 1000
        for job, result in zip(batch, results, strict=True):
            if job.future.done():
                continue
            if isinstance(result, BaseException):
                err = wrap_exception(result)
                self._counters.failed += 1
                if not err.is_client_error and not err.logged:
                    err.logged = True
                    self._log.error(
                        "Inference failed on %s: %s", self.model_id, err.message,
                        exc_info=(type(result), result, result.__traceback__),
                        extra={"code": err.code.value, "model_id": self.model_id,
                               "request_id": job.request_id},
                    )
                job.future.set_exception(err)
            else:
                self._counters.completed += 1
                job.future.set_result((result, JobTimings(
                    queue_wait_ms=(started - job.enqueued) * 1000,
                    compute_ms=compute_ms,
                    batch_id=batch_id,
                    batch_size=len(batch),
                )))
        self._notify()

    def _notify(self) -> None:
        """Throttled state-change callback (the UI shows live active/queued counters)."""
        if self.on_change is None or self._notify_handle is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.on_change()
            return

        def fire() -> None:
            self._notify_handle = None
            if self.on_change:
                self.on_change()

        self._notify_handle = loop.call_later(0.1, fire)
