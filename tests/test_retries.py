import asyncio
import pytest
from retries import with_retry


async def test_succeeds_on_first_attempt():
    calls = []

    async def fn():
        calls.append(1)
        return "ok"

    result = await with_retry(fn, attempts=3, base_delay=0)
    assert result == "ok"
    assert len(calls) == 1


async def test_retries_on_failure_then_succeeds():
    calls = []

    async def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("transient")
        return "recovered"

    result = await with_retry(fn, attempts=3, base_delay=0)
    assert result == "recovered"
    assert len(calls) == 3


async def test_raises_after_max_attempts():
    async def fn():
        raise RuntimeError("always fails")

    with pytest.raises(RuntimeError, match="always fails"):
        await with_retry(fn, attempts=3, base_delay=0)


async def test_attempt_count_matches_max():
    calls = []

    async def fn():
        calls.append(1)
        raise OSError("network")

    with pytest.raises(OSError):
        await with_retry(fn, attempts=4, base_delay=0)
    assert len(calls) == 4


async def test_timeout_raises_on_slow_call():
    async def fn():
        await asyncio.sleep(10)
        return "too late"

    with pytest.raises((TimeoutError, asyncio.TimeoutError)):
        await with_retry(fn, attempts=2, base_delay=0, timeout=0.01)


async def test_cancelled_error_is_not_retried():
    calls = []

    async def fn():
        calls.append(1)
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await with_retry(fn, attempts=3, base_delay=0)
    assert len(calls) == 1  # no retry after cancellation


async def test_zero_attempts_raises_valueerror():
    async def fn():
        return "should not run"

    with pytest.raises(ValueError, match="attempts"):
        await with_retry(fn, attempts=0)
