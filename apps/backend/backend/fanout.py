"""Hand events from worker threads to async subscribers (the SSE routes).

Why: the build runner (`jobs.py`) and the Keeper's runs (`keeper_runs.py`) both publish from a
worker thread to queues that belong to an event loop. This module holds the parts they share;
each owner keeps its own lock and subscriber set, and decides which subscriber gets which event.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(eq=False)
class Subscriber[T]:
    slug: str | None  # None = every company
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[T | None]  # None: the stream is over


def deliver[T](sub: Subscriber[T], item: T | None) -> bool:
    """Put `item` on the subscriber's queue, from any thread. False when its event loop is
    closed: nobody is listening any more, so the owner drops the subscriber."""
    try:
        sub.loop.call_soon_threadsafe(sub.queue.put_nowait, item)
    except RuntimeError:
        return False
    return True


class Subscription[T]:
    """What a `subscribe` returns: an async iterator over one subscriber's queue that stops at
    a None. Not an async generator, because a generator that never started skips its `finally`
    on `aclose()`, which would leave the subscriber registered for good."""

    def __init__(self, unsubscribe: Callable[[], None], queue: asyncio.Queue[T | None]):
        self._unsubscribe = unsubscribe
        self._queue = queue

    def __aiter__(self) -> Subscription[T]:
        return self

    async def __anext__(self) -> T:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def aclose(self) -> None:
        self._unsubscribe()
