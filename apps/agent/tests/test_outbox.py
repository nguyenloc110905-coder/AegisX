from datetime import UTC, datetime
from pathlib import Path

from aegisx_agent.events import NormalizedEvent
from aegisx_agent.outbox import Outbox


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
