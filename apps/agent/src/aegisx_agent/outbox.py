import asyncio
import sqlite3
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from aegisx_agent.events import NormalizedEvent
from aegisx_agent.local_store import (
    LocalStoreCapacityError,
    LocalStoreIntegrityError,
    LocalStoreMigrationError,
    LocalTelemetryStore,
)
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

    @property
    def delivery_only(self) -> bool:
        return False


class LegacyDeliveryStore:
    """Read and drain an intact v0 outbox without appending new telemetry."""

    def __init__(self, path: Path) -> None:
        LocalTelemetryStore._prepare_path(path)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        if self._connection.execute("PRAGMA user_version").fetchone() != (0,):
            self._connection.close()
            raise LocalStoreMigrationError("database is not a legacy v0 outbox")
        tables = {
            str(row[0])
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if not {"pending_events", "quarantined_events"}.issubset(tables):
            self._connection.close()
            raise LocalStoreMigrationError("legacy outbox schema is incomplete")

    @property
    def delivery_only(self) -> bool:
        return True

    def enqueue(self, events: list[NormalizedEvent]) -> int:
        raise LocalStoreCapacityError("legacy fallback is delivery-only")

    def peek(self, limit: int) -> list[NormalizedEvent]:
        rows = self._connection.execute(
            "SELECT event_id, payload FROM pending_events ORDER BY sequence LIMIT ?",
            (limit,),
        ).fetchall()
        events: list[NormalizedEvent] = []
        try:
            for event_id, payload in rows:
                event = NormalizedEvent.model_validate_json(str(payload))
                if event.id != str(event_id):
                    raise LocalStoreIntegrityError("legacy event UUID does not match payload")
                events.append(event)
        except ValidationError as error:
            raise LocalStoreIntegrityError("legacy pending payload is malformed") from error
        return events

    def acknowledge(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        placeholders = ",".join("?" for _ in event_ids)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                f"DELETE FROM pending_events WHERE event_id IN ({placeholders})",  # noqa: S608
                event_ids,
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def quarantine(self, event_ids: list[str], reason: str) -> None:
        if not event_ids:
            return
        if len(reason) > 64 or not reason.startswith("http_") or not reason[5:].isdigit():
            raise ValueError("quarantine reason must be a bounded HTTP category")
        placeholders = ",".join("?" for _ in event_ids)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            rows = self._connection.execute(
                f"SELECT event_id, payload FROM pending_events "  # noqa: S608
                f"WHERE event_id IN ({placeholders})",
                event_ids,
            ).fetchall()
            self._connection.executemany(
                "INSERT OR REPLACE INTO quarantined_events (event_id, payload, reason) "
                "VALUES (?, ?, ?)",
                [(row[0], row[1], reason) for row in rows],
            )
            self._connection.execute(
                f"DELETE FROM pending_events WHERE event_id IN ({placeholders})",  # noqa: S608
                event_ids,
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) FROM pending_events").fetchone()
        return int(row[0]) if row else 0

    def quarantine_count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) FROM quarantined_events").fetchone()
        return int(row[0]) if row else 0

    def quarantine_reasons(self) -> list[str]:
        rows = self._connection.execute(
            "SELECT reason FROM quarantined_events ORDER BY sequence"
        ).fetchall()
        return [str(row[0]) for row in rows]

    def delivery_state(self, event_id: str) -> DeliveryState | None:
        pending = self._connection.execute(
            "SELECT 1 FROM pending_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        if pending:
            return DeliveryState.PENDING
        quarantined = self._connection.execute(
            "SELECT 1 FROM quarantined_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return DeliveryState.QUARANTINED if quarantined else None

    def close(self) -> None:
        self._connection.close()


def _open_store(
    path: Path, max_events: int, max_payload_bytes: int
) -> Outbox | LegacyDeliveryStore:
    try:
        return Outbox(path, max_events, max_payload_bytes)
    except LocalStoreMigrationError as migration_error:
        try:
            return LegacyDeliveryStore(path)
        except LocalStoreMigrationError as fallback_error:
            raise migration_error from fallback_error


class AsyncOutbox:
    """Serialized async adapter retained for existing agent call sites."""

    def __init__(self, outbox: Outbox | LegacyDeliveryStore) -> None:
        self._outbox = outbox
        self._lock = asyncio.Lock()

    @classmethod
    async def open(
        cls,
        path: Path,
        max_events: int,
        max_payload_bytes: int = DEFAULT_LOCAL_TELEMETRY_MAX_BYTES,
    ) -> "AsyncOutbox":
        outbox = await _run_in_thread(_open_store, path, max_events, max_payload_bytes)
        return cls(outbox)

    @property
    def delivery_only(self) -> bool:
        return self._outbox.delivery_only

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
