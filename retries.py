import asyncio
import logging

logger = logging.getLogger("quill.retries")


async def with_retry(
    coro_fn,
    *,
    attempts: int = 3,
    base_delay: float = 2.0,
    timeout: float | None = None,
    label: str = "",
):
    """Call coro_fn() up to `attempts` times with exponential backoff.

    Each attempt is optionally wrapped in asyncio.wait_for(timeout=timeout).
    Raises the last exception once all attempts are exhausted.
    """
    last_exc: BaseException | None = None
    tag = label or "call"
    for attempt in range(1, attempts + 1):
        try:
            coro = coro_fn()
            if timeout is not None:
                return await asyncio.wait_for(coro, timeout=timeout)
            return await coro
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            last_exc = exc
            logger.warning("%s timed out (attempt %d/%d)", tag, attempt, attempts)
        except Exception as exc:
            last_exc = exc
            logger.warning("%s error (attempt %d/%d): %s", tag, attempt, attempts, exc)
        if attempt < attempts:
            await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
    raise last_exc
