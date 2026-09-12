import asyncio
from collections.abc import Callable
from pathlib import Path

from aegisx_agent.events import NormalizedEvent
from aegisx_agent.local_store import LocalTelemetryStore
from aegisx_agent.local_types import DeliveryState

DEFAULT_LOCAL_TELEMETRY_MAX_BYTES = 256 * 1024 * 1024


async def _run_in_thread[**P, T](operation: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    task = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        finally:
            raise


class Outbox(LocalTelemetryStore):
    """Compatibility name for the local telemetry store during schema-v2 rollout."""

    def __init__(
        self,
        path: Path,
        max_events: int,
        max_payload_bytes: int = DEFAULT_LOCAL_TELEMETRY_MAX_BYTES,
    ) -> None:
        super().__init__(path, max_events, max_payload_bytes)


class AsyncOutbox:
    """Serialized async adapter retained for existing agent call sites."""

    def __init__(self, outbox: Outbox) -> None:
        self._outbox = outbox
        self._lock = asyncio.Lock()

    @classmethod
    async def open(
        cls,
        path: Path,
        max_events: int,
        max_payload_bytes: int = DEFAULT_LOCAL_TELEMETRY_MAX_BYTES,
    ) -> "AsyncOutbox":
        outbox = await _run_in_thread(Outbox, path, max_events, max_payload_bytes)
        return cls(outbox)

    async def enqueue(self, events: list[NormalizedEvent]) -> int:
        async with self._lock:
            return await _run_in_thread(self._outbox.enqueue, events)

    async def peek(self, limit: int) -> list[NormalizedEvent]:
        async with self._lock:
            return await _run_in_thread(self._outbox.peek, limit)

    async def acknowledge(self, event_ids: list[str]) -> None:
        async with self._lock:
            await _run_in_thread(self._outbox.acknowledge, event_ids)

    async def quarantine(self, event_ids: list[str], reason: str) -> None:
        async with self._lock:
            await _run_in_thread(self._outbox.quarantine, event_ids, reason)

    async def count(self) -> int:
        async with self._lock:
            return await _run_in_thread(self._outbox.count)

    async def quarantine_count(self) -> int:
        async with self._lock:
            return await _run_in_thread(self._outbox.quarantine_count)

    async def quarantine_reasons(self) -> list[str]:
        async with self._lock:
            return await _run_in_thread(self._outbox.quarantine_reasons)

    async def delivery_state(self, event_id: str) -> DeliveryState | None:
        async with self._lock:
            return await _run_in_thread(self._outbox.delivery_state, event_id)

    async def close(self) -> None:
        async with self._lock:
            await _run_in_thread(self._outbox.close)


AsyncLocalTelemetryStore = AsyncOutbox
