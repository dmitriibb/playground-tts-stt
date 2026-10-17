import asyncio
import time

import pytest

from common.errors import AppError, ErrorCode
from common.runner import ModelRunner
from common.schemas import RunnerConfig, RunnerConfigPatch


def slow(x):
    time.sleep(0.05)
    return x * 2


def batch_fn(xs):
    time.sleep(0.05)
    return [x * 10 for x in xs]


async def test_queue_full_rejects():
    runner = ModelRunner("m", RunnerConfig(max_active=1, max_queued=1), slow)
    runner.start()
    try:
        first = asyncio.create_task(runner.submit(1))
        await asyncio.sleep(0.01)  # first one is running
        second = asyncio.create_task(runner.submit(2))  # waits in the queue
        await asyncio.sleep(0.01)
        with pytest.raises(AppError) as exc:
            await runner.submit(3)
        assert exc.value.code == ErrorCode.QUEUE_FULL
        assert (await first)[0] == 2
        assert (await second)[0] == 4
        assert runner.state().rejected == 1
    finally:
        await runner.stop()


async def test_dynamic_batching_groups_compatible_jobs():
    runner = ModelRunner("m", RunnerConfig(max_active=1, max_batch_size=4, max_wait_ms=100), slow, batch_fn)
    runner.start()
    try:
        results = await asyncio.gather(*(runner.submit(i, batch_key="k") for i in range(4)))
        values = [r for r, _ in results]
        timings = [t for _, t in results]
        assert values == [0, 10, 20, 30]
        assert {t.batch_size for t in timings} == {4}
        assert len({t.batch_id for t in timings}) == 1
    finally:
        await runner.stop()


async def test_jobs_without_key_are_never_batched():
    runner = ModelRunner("m", RunnerConfig(max_active=1, max_batch_size=4, max_wait_ms=50), slow, batch_fn)
    runner.start()
    try:
        results = await asyncio.gather(*(runner.submit(i) for i in range(3)))
        assert [r for r, _ in results] == [0, 2, 4]
        assert all(t.batch_size == 1 for _, t in results)
        # serial execution: later jobs waited in the queue
        assert max(t.queue_wait_ms for _, t in results) >= 40
    finally:
        await runner.stop()


async def test_parallel_workers():
    runner = ModelRunner("m", RunnerConfig(max_active=3), slow)
    runner.start()
    try:
        t0 = time.perf_counter()
        await asyncio.gather(*(runner.submit(i) for i in range(3)))
        assert time.perf_counter() - t0 < 0.13  # 3 x 50 ms in parallel, not 150 ms
    finally:
        await runner.stop()


async def test_reconfigure_max_active_live():
    runner = ModelRunner("m", RunnerConfig(max_active=1), slow)
    runner.start()
    try:
        await runner.submit(1)
        runner.reconfigure(RunnerConfigPatch(max_active=3))
        t0 = time.perf_counter()
        results = await asyncio.gather(*(runner.submit(i) for i in range(3)))
        assert [r for r, _ in results] == [0, 2, 4]
        assert time.perf_counter() - t0 < 0.14
        assert runner.state().max_active == 3
    finally:
        await runner.stop()


async def test_engine_error_becomes_inference_failed():
    def boom(_):
        raise RuntimeError("kaboom")

    runner = ModelRunner("m", RunnerConfig(), boom)
    runner.start()
    try:
        with pytest.raises(AppError) as exc:
            await runner.submit(1)
        assert exc.value.code == ErrorCode.INFERENCE_FAILED
        assert "kaboom" in exc.value.message
        assert runner.state().failed == 1
    finally:
        await runner.stop()


async def test_stop_cancels_queued_jobs():
    runner = ModelRunner("m", RunnerConfig(max_active=1, max_queued=10), slow)
    runner.start()
    running = asyncio.create_task(runner.submit(1))
    await asyncio.sleep(0.01)
    queued = asyncio.create_task(runner.submit(2))
    await asyncio.sleep(0.01)
    await runner.stop()
    with pytest.raises(AppError) as exc:
        await queued
    assert exc.value.code == ErrorCode.CANCELLED
    running.cancel()
