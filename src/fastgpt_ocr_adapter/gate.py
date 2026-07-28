from __future__ import annotations

import asyncio
from types import TracebackType


class QueueFullError(Exception):
    """There is no execution slot or queue position available."""


class QueueTimeoutError(Exception):
    """A queued request waited too long for an execution slot."""


class RequestGate:
    def __init__(
        self,
        max_concurrent_requests: int,
        max_queued_requests: int,
        queue_timeout_seconds: float,
    ) -> None:
        self.max_concurrent_requests = max_concurrent_requests
        self.max_queued_requests = max_queued_requests
        self.queue_timeout_seconds = queue_timeout_seconds
        self._condition = asyncio.Condition()
        self._active = 0
        self._queued = 0

    @property
    def active(self) -> int:
        return self._active

    @property
    def queued(self) -> int:
        return self._queued

    async def __aenter__(self) -> RequestGate:
        async with self._condition:
            if self._active >= self.max_concurrent_requests:
                if self._queued >= self.max_queued_requests:
                    raise QueueFullError
                self._queued += 1
                try:
                    await asyncio.wait_for(
                        self._condition.wait_for(
                            lambda: self._active < self.max_concurrent_requests
                        ),
                        timeout=self.queue_timeout_seconds,
                    )
                except TimeoutError as exc:
                    raise QueueTimeoutError from exc
                finally:
                    self._queued -= 1
            self._active += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        async with self._condition:
            self._active -= 1
            self._condition.notify(1)
