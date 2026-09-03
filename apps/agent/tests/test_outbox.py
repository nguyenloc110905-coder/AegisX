import asyncio
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegisx_agent.events import NormalizedEvent
from aegisx_agent.outbox import AsyncOutbox, Outbox


def event(event_id: str) -> NormalizedEvent:
    return NormalizedEvent(
        id=event_id,
        timestamp=datetime.now(UTC),
        event_type="system.status",
        source="test",
        severity_hint="normal",
        data={"hostname": "test"},
        metadata={},
    )


def test_outbox_persists_events_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "outbox.sqlite3"
    first = Outbox(path, max_events=10)
    first.enqueue([event("00000000-0000-0000-0000-000000000001")])
    first.close()

    second = Outbox(path, max_events=10)

    assert second.count() == 1
    assert second.peek(10)[0].id == "00000000-0000-0000-0000-000000000001"
    second.close()


def test_outbox_evicts_oldest_when_bound_is_exceeded(tmp_path: Path) -> None:
    outbox = Outbox(tmp_path / "outbox.sqlite3", max_events=2)
    events = [
        event("00000000-0000-0000-0000-000000000001"),
        event("00000000-0000-0000-0000-000000000002"),
        event("00000000-0000-0000-0000-000000000003"),
    ]

    evicted = outbox.enqueue(events)

    assert evicted == 1
    assert [item.id for item in outbox.peek(10)] == [events[1].id, events[2].id]
    outbox.close()


def test_outbox_acknowledges_delivered_events(tmp_path: Path) -> None:
    outbox = Outbox(tmp_path / "outbox.sqlite3", max_events=10)
    events = [
        event("00000000-0000-0000-0000-000000000001"),
        event("00000000-0000-0000-0000-000000000002"),
    ]
    outbox.enqueue(events)

    outbox.acknowledge([events[0].id])

    assert [item.id for item in outbox.peek(10)] == [events[1].id]
    outbox.close()


def test_outbox_quarantines_permanently_invalid_events(tmp_path: Path) -> None:
    outbox = Outbox(tmp_path / "outbox.sqlite3", max_events=10)
    invalid = event("00000000-0000-0000-0000-000000000001")
    outbox.enqueue([invalid])

    outbox.quarantine([invalid.id], reason="http_422")

    assert outbox.count() == 0
    assert outbox.quarantine_count() == 1
    assert outbox.quarantine_reasons() == ["http_422"]
    outbox.close()


@pytest.mark.asyncio
async def test_async_outbox_preserves_order_idempotency_and_quarantine(tmp_path: Path) -> None:
    outbox = await AsyncOutbox.open(tmp_path / "outbox.sqlite3", max_events=10)
    first = event("00000000-0000-0000-0000-000000000001")
    second = event("00000000-0000-0000-0000-000000000002")

    await outbox.enqueue([first, second, first])
    assert [item.id for item in await outbox.peek(10)] == [first.id, second.id]

    await outbox.acknowledge([first.id])
    await outbox.quarantine([second.id], reason="http_422")

    assert await outbox.count() == 0
    assert await outbox.quarantine_count() == 1
    assert await outbox.quarantine_reasons() == ["http_422"]
    await outbox.close()


@pytest.mark.asyncio
async def test_async_outbox_runs_calls_off_loop_and_serializes_connection_access(
    tmp_path: Path,
) -> None:
    outbox = await AsyncOutbox.open(tmp_path / "outbox.sqlite3", max_events=10)
    main_thread = threading.get_ident()
    active = 0
    maximum_active = 0
    worker_threads: list[int] = []
    counter_lock = threading.Lock()

    def inspected_count() -> int:
        nonlocal active, maximum_active
        with counter_lock:
            active += 1
            maximum_active = max(maximum_active, active)
            worker_threads.append(threading.get_ident())
        time.sleep(0.02)
        with counter_lock:
            active -= 1
        return 0

    outbox._outbox.count = inspected_count

    assert await asyncio.gather(outbox.count(), outbox.count()) == [0, 0]
    assert maximum_active == 1
    assert all(worker_thread != main_thread for worker_thread in worker_threads)
    await outbox.close()


@pytest.mark.asyncio
async def test_async_outbox_cancellation_does_not_release_connection_while_worker_runs(
    tmp_path: Path,
) -> None:
    outbox = await AsyncOutbox.open(tmp_path / "outbox.sqlite3", max_events=10)
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    calls = 0

    def blocking_count() -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            release_first.wait(timeout=1)
        else:
            second_started.set()
        return 0

    outbox._outbox.count = blocking_count
    first = asyncio.create_task(outbox.count())
    assert await asyncio.to_thread(first_started.wait, 1)

    first.cancel()
    second = asyncio.create_task(outbox.count())
    await asyncio.sleep(0.02)
    assert not second_started.is_set()

    release_first.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert await second == 0
    await outbox.close()
