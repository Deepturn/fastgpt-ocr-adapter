from __future__ import annotations

import asyncio

import pytest

from fastgpt_ocr_adapter.gate import QueueFullError, QueueTimeoutError, RequestGate


@pytest.mark.asyncio
async def test_waiting_request_runs_after_active_request() -> None:
    gate = RequestGate(1, 1, 1)
    first_started = asyncio.Event()
    release = asyncio.Event()
    second_started = asyncio.Event()

    async def first() -> None:
        async with gate:
            first_started.set()
            await release.wait()

    async def second() -> None:
        async with gate:
            second_started.set()

    first_task = asyncio.create_task(first())
    await first_started.wait()
    second_task = asyncio.create_task(second())
    await asyncio.sleep(0)
    assert gate.active == 1
    assert gate.queued == 1
    assert not second_started.is_set()
    release.set()
    await asyncio.gather(first_task, second_task)
    assert second_started.is_set()
    assert gate.active == 0
    assert gate.queued == 0


@pytest.mark.asyncio
async def test_full_queue_is_rejected() -> None:
    gate = RequestGate(1, 1, 1)
    await gate.__aenter__()
    waiting = asyncio.create_task(gate.__aenter__())
    await asyncio.sleep(0)
    with pytest.raises(QueueFullError):
        await gate.__aenter__()
    await gate.__aexit__(None, None, None)
    await waiting
    await gate.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_queue_wait_timeout() -> None:
    gate = RequestGate(1, 1, 0.01)
    await gate.__aenter__()
    with pytest.raises(QueueTimeoutError):
        await gate.__aenter__()
    await gate.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_zero_length_queue_rejects_immediately() -> None:
    gate = RequestGate(1, 0, 1)
    await gate.__aenter__()
    with pytest.raises(QueueFullError):
        await gate.__aenter__()
    await gate.__aexit__(None, None, None)
