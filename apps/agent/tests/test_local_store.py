import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegisx_agent.events import NormalizedEvent
from aegisx_agent.local_store import (
    LocalStoreIntegrityError,
    LocalStoreMigrationError,
    LocalStorePathError,
    LocalTelemetryStore,
)
from aegisx_agent.local_types import DeliveryState

FIXED_TIME = datetime(2026, 9, 12, 12, tzinfo=UTC)
FIRST_ID = "00000000-0000-0000-0000-000000000001"
SECOND_ID = "00000000-0000-0000-0000-000000000002"


def event(event_id: str, event_type: str = "system.status", value: int = 1) -> NormalizedEvent:
    return NormalizedEvent(
        id=event_id,
        timestamp=FIXED_TIME,
        event_type=event_type,
        source="test",
        severity_hint="normal",
        data={"value": value},
        metadata={},
    )


def make_store(path: Path) -> LocalTelemetryStore:
    return LocalTelemetryStore(
        path,
        max_events=100,
        max_payload_bytes=1024 * 1024,
        clock=lambda: FIXED_TIME,
    )


def test_fresh_store_is_private_wal_full_and_schema_v2(tmp_path: Path) -> None:
    path = tmp_path / "state" / "outbox.sqlite3"
    store = make_store(path)

    assert store.enqueue([event(FIRST_ID)]) == 0
    store.close()

    assert os.stat(path.parent).st_mode & 0o777 == 0o700
    assert os.stat(path).st_mode & 0o777 == 0o600
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (2,)
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert connection.execute("PRAGMA synchronous").fetchone() == (2,)
        row = connection.execute(
            "SELECT sequence, event_id, priority, delivery_state, payload, payload_bytes, "
            "length(payload_hash) FROM local_events"
        ).fetchone()
        assert row[:4] == (1, FIRST_ID, "OPERATIONAL", "PENDING")
        assert row[5:] == (len(str(row[4]).encode("utf-8")), 64)


def test_enqueue_is_idempotent_only_for_identical_immutable_payload(tmp_path: Path) -> None:
    store = make_store(tmp_path / "outbox.sqlite3")
    original = event(FIRST_ID)

    assert store.enqueue([original, original]) == 0
    assert store.count() == 1

    with pytest.raises(LocalStoreIntegrityError, match="conflicting immutable payload"):
        store.enqueue([event(FIRST_ID, value=2)])
    assert store.peek(10) == [original]
    store.close()


def test_acknowledge_keeps_journal_evidence_outside_delivery_view(tmp_path: Path) -> None:
    store = make_store(tmp_path / "outbox.sqlite3")
    item = event(FIRST_ID)
    store.enqueue([item])

    store.acknowledge([item.id])

    assert store.peek(10) == []
    assert store.count() == 0
    assert store.delivery_state(item.id) is DeliveryState.ACKED

    store.acknowledge([item.id, SECOND_ID])
    assert store.delivery_state(item.id) is DeliveryState.ACKED
    store.close()


def test_acknowledge_rolls_back_complete_transition_on_sqlite_failure(tmp_path: Path) -> None:
    store = make_store(tmp_path / "outbox.sqlite3")
    first = event(FIRST_ID)
    second = event(SECOND_ID)
    store.enqueue([first, second])
    store._connection.execute(
        "CREATE TRIGGER reject_second_ack BEFORE UPDATE ON local_events "
        f"WHEN OLD.event_id = '{SECOND_ID}' BEGIN SELECT RAISE(ABORT, 'test'); END"
    )

    with pytest.raises(sqlite3.IntegrityError):
        store.acknowledge([first.id, second.id])

    assert store.delivery_state(first.id) is DeliveryState.PENDING
    assert store.delivery_state(second.id) is DeliveryState.PENDING
    store.close()


def test_quarantine_keeps_journal_evidence_without_retry(tmp_path: Path) -> None:
    store = make_store(tmp_path / "outbox.sqlite3")
    item = event(FIRST_ID)
    store.enqueue([item])

    store.quarantine([item.id], reason="http_422")

    assert store.peek(10) == []
    assert store.quarantine_count() == 1
    assert store.quarantine_reasons() == ["http_422"]
    assert store.delivery_state(item.id) is DeliveryState.QUARANTINED
    store.close()


def test_store_rejects_symlink_database_target(tmp_path: Path) -> None:
    target = tmp_path / "target.sqlite3"
    target.touch()
    path = tmp_path / "outbox.sqlite3"
    path.symlink_to(target)

    with pytest.raises(LocalStorePathError, match="symlink"):
        make_store(path)


def test_store_refuses_schema_newer_than_supported(tmp_path: Path) -> None:
    path = tmp_path / "outbox.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version = 3")

    with pytest.raises(LocalStoreMigrationError, match="newer schema version"):
        make_store(path)


def _create_legacy_store(path: Path, *, malformed: bool = False) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE pending_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE quarantined_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                reason TEXT NOT NULL,
                quarantined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            "INSERT INTO pending_events (event_id, payload) VALUES (?, ?)",
            (FIRST_ID, "{" if malformed else event(FIRST_ID).model_dump_json()),
        )
        connection.execute(
            "INSERT INTO quarantined_events (event_id, payload, reason) VALUES (?, ?, ?)",
            (SECOND_ID, event(SECOND_ID, "process.started").model_dump_json(), "http_422"),
        )


def test_legacy_pending_and_quarantine_are_migrated_once(tmp_path: Path) -> None:
    path = tmp_path / "outbox.sqlite3"
    _create_legacy_store(path)

    store = make_store(path)
    assert [item.id for item in store.peek(10)] == [FIRST_ID]
    assert store.quarantine_count() == 1
    assert store.quarantine_reasons() == ["http_422"]
    store.close()

    reopened = make_store(path)
    assert reopened.count() == 1
    assert reopened.quarantine_count() == 1
    reopened.close()
    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "pending_events" not in tables
        assert "quarantined_events" not in tables


def test_malformed_legacy_payload_rolls_back_complete_migration(tmp_path: Path) -> None:
    path = tmp_path / "outbox.sqlite3"
    _create_legacy_store(path, malformed=True)

    with pytest.raises(LocalStoreMigrationError, match="legacy migration failed"):
        make_store(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "pending_events" in tables
        assert "quarantined_events" in tables
        assert "local_events" not in tables
