import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aegisx_agent.events import NormalizedEvent
from aegisx_agent.local_store import (
    LocalStoreCapacityError,
    LocalStoreError,
    LocalStoreIntegrityError,
    LocalStoreMigrationError,
    LocalStorePathError,
    LocalTelemetryStore,
)
from aegisx_agent.local_types import CoverageGapCategory, DeliveryState

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

    with pytest.raises(LocalStoreError, match="acknowledgement"):
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


def test_legacy_duplicate_uuid_across_states_refuses_lossy_migration(tmp_path: Path) -> None:
    path = tmp_path / "outbox.sqlite3"
    _create_legacy_store(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE quarantined_events SET event_id = ?, payload = ?",
            (FIRST_ID, event(FIRST_ID).model_dump_json()),
        )

    with pytest.raises(LocalStoreMigrationError, match="legacy migration failed"):
        make_store(path)

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pending_events").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM quarantined_events").fetchone() == (1,)


def test_verify_reports_valid_rows_and_first_bounded_integrity_failure(tmp_path: Path) -> None:
    store = make_store(tmp_path / "outbox.sqlite3")
    store.enqueue([event(FIRST_ID), event(SECOND_ID)])

    valid = store.verify()
    assert valid.valid is True
    assert valid.checked_events == 2
    assert valid.first_bad_sequence is None
    assert valid.failure_category is None

    store._connection.execute(
        "UPDATE local_events SET payload_hash = ? WHERE event_id = ?",
        ("0" * 64, SECOND_ID),
    )
    store._connection.commit()

    invalid = store.verify()
    assert invalid.valid is False
    assert invalid.checked_events == 1
    assert invalid.first_bad_sequence == 2
    assert invalid.failure_category == "payload_hash_mismatch"
    assert FIRST_ID not in repr(invalid)
    assert SECOND_ID not in repr(invalid)
    store.close()


def test_verify_returns_bounded_result_for_invalid_size_metadata(tmp_path: Path) -> None:
    store = make_store(tmp_path / "outbox.sqlite3")
    store.enqueue([event(FIRST_ID)])
    store._connection.execute("UPDATE local_events SET payload_bytes = 'invalid'")
    store._connection.commit()

    result = store.verify()

    assert result.valid is False
    assert result.first_bad_sequence == 1
    assert result.failure_category == "payload_size_mismatch"
    store.close()


def test_data_status_contains_counts_and_no_raw_payload(tmp_path: Path) -> None:
    path = tmp_path / "outbox.sqlite3"
    store = make_store(path)
    first = event(FIRST_ID, "system.status")
    second = event(SECOND_ID, "process.started")
    store.enqueue([first, second])
    store.acknowledge([first.id])
    store.quarantine([second.id], "http_422")

    status = store.data_status()

    assert status.policy_version == 1
    assert status.schema_version == 2
    assert status.event_count == 2
    assert status.pending_count == 0
    assert status.acknowledged_count == 1
    assert status.quarantined_count == 1
    assert status.logical_payload_bytes > 0
    assert status.database_file_bytes == path.stat().st_size
    assert [item.event_type for item in status.event_types] == [
        "process.started",
        "system.status",
    ]
    assert "hostname" not in repr(status)
    store.close()


def test_clock_rollback_keeps_recorded_time_monotonic_and_records_gap(tmp_path: Path) -> None:
    times = iter(
        [
            datetime(2026, 9, 12, 12, tzinfo=UTC),
            datetime(2026, 9, 12, 11, tzinfo=UTC),
        ]
    )
    store = LocalTelemetryStore(
        tmp_path / "outbox.sqlite3",
        max_events=100,
        max_payload_bytes=1024 * 1024,
        clock=lambda: next(times),
    )
    store.enqueue([event(FIRST_ID)])
    store.enqueue([event(SECOND_ID)])

    rows = store._connection.execute(
        "SELECT recorded_at FROM local_events ORDER BY sequence"
    ).fetchall()
    assert rows[0][0] == rows[1][0]
    gaps = store._connection.execute("SELECT category, reason FROM coverage_gaps").fetchall()
    assert gaps == [("CLOCK_REGRESSION", "local clock moved backwards")]
    store.close()


def test_recorded_at_is_normalized_to_utc(tmp_path: Path) -> None:
    local_time = datetime.fromisoformat("2026-09-12T19:00:00+07:00")
    store = LocalTelemetryStore(
        tmp_path / "outbox.sqlite3",
        max_events=100,
        max_payload_bytes=1024 * 1024,
        clock=lambda: local_time,
    )

    store.enqueue([event(FIRST_ID)])

    recorded = store._connection.execute("SELECT recorded_at FROM local_events").fetchone()[0]
    assert recorded == "2026-09-12T12:00:00+00:00"
    store.close()


def test_retention_cutoff_is_inclusive_and_preserves_noneligible_states(tmp_path: Path) -> None:
    evaluation = datetime(2026, 9, 12, 12, tzinfo=UTC)
    store = make_store(tmp_path / "outbox.sqlite3")
    events = [
        event(FIRST_ID, "network.listener_observed"),
        event(SECOND_ID, "network.connection_observed"),
        event("00000000-0000-0000-0000-000000000003", "process.resource_usage"),
        event("00000000-0000-0000-0000-000000000004", "future.signal"),
    ]
    store.enqueue(events)
    store.acknowledge([item.id for item in events])
    cutoff = evaluation.replace(day=11)
    store._connection.execute(
        "UPDATE local_events SET recorded_at = ? WHERE event_id = ?",
        ((cutoff.replace(microsecond=1)).isoformat(), events[0].id),
    )
    store._connection.execute(
        "UPDATE local_events SET recorded_at = ? WHERE event_id = ?",
        (cutoff.isoformat(), events[1].id),
    )
    store._connection.execute(
        "UPDATE local_events SET recorded_at = ?, delivery_state = 'PENDING', "
        "acknowledged_at = NULL WHERE event_id = ?",
        ((cutoff.replace(microsecond=0) - timedelta(microseconds=1)).isoformat(), events[2].id),
    )
    store._connection.execute(
        "UPDATE local_events SET recorded_at = ? WHERE event_id = ?",
        ((cutoff - timedelta(days=100)).isoformat(), events[3].id),
    )
    store._connection.commit()

    report = store.dry_run(evaluation)
    bulk = next(rule for rule in report.rules if rule.priority == "BULK")
    assert bulk.eligible_events == 1

    result = store.prune(evaluation, batch_size=1)
    repeated = store.prune(evaluation, batch_size=1)
    assert result.deleted_events == 1
    assert repeated.deleted_events == 0
    assert store.delivery_state(events[0].id) is DeliveryState.ACKED
    assert store.delivery_state(events[1].id) is None
    assert store.delivery_state(events[2].id) is DeliveryState.PENDING
    assert store.delivery_state(events[3].id) is DeliveryState.ACKED
    store.close()


def test_capacity_prunes_only_expired_acknowledged_data_or_records_gap(tmp_path: Path) -> None:
    path = tmp_path / "outbox.sqlite3"
    store = LocalTelemetryStore(
        path, max_events=100, max_payload_bytes=350, clock=lambda: FIXED_TIME
    )
    expired = event(FIRST_ID, "process.resource_usage")
    protected = event(SECOND_ID, "process.started")
    store.enqueue([expired])
    store.acknowledge([expired.id])
    store._connection.execute(
        "UPDATE local_events SET recorded_at = ? WHERE event_id = ?",
        ((FIXED_TIME - timedelta(days=2)).isoformat(), expired.id),
    )
    store._connection.commit()

    store.enqueue([protected])
    assert store.delivery_state(expired.id) is None
    assert store.delivery_state(protected.id) is DeliveryState.PENDING

    too_large = event("00000000-0000-0000-0000-000000000003", "process.started", value=999)
    with pytest.raises(LocalStoreCapacityError):
        store.enqueue([too_large])
    assert store.delivery_state(protected.id) is DeliveryState.PENDING
    gap = store._connection.execute(
        "SELECT category, dropped_event_count FROM coverage_gaps ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert gap == (CoverageGapCategory.STORAGE_LIMIT.value, 1)
    store.close()


def test_write_failure_uses_bounded_sidecar_and_imports_it_after_recovery(
    tmp_path: Path,
) -> None:
    path = tmp_path / "outbox.sqlite3"
    store = make_store(path)
    store._connection.execute(
        "CREATE TRIGGER reject_insert BEFORE INSERT ON local_events "
        "BEGIN SELECT RAISE(ABORT, 'sensitive raw failure'); END"
    )

    with pytest.raises(LocalStoreError, match="local telemetry write failed"):
        store.enqueue([event(FIRST_ID)])

    sidecar = tmp_path / "coverage-gap.json"
    sidecar_text = sidecar.read_text(encoding="utf-8")
    assert sidecar.stat().st_mode & 0o777 == 0o600
    assert "STORAGE_WRITE_FAILURE" in sidecar_text
    assert FIRST_ID not in sidecar_text
    assert "sensitive" not in sidecar_text
    store.close()

    recovered = make_store(path)
    assert not sidecar.exists()
    assert recovered.data_status().coverage_gap_count == 1
    recovered.close()


def test_sidecar_writer_refuses_symlink_without_touching_target(tmp_path: Path) -> None:
    store = make_store(tmp_path / "outbox.sqlite3")
    target = tmp_path / "unrelated.json"
    target.write_text('{"keep":true}', encoding="utf-8")
    (tmp_path / "coverage-gap.json").symlink_to(target)

    with pytest.raises(LocalStorePathError, match="sidecar"):
        store._write_gap_sidecar(
            CoverageGapCategory.STORAGE_WRITE_FAILURE,
            FIXED_TIME,
            1,
        )

    assert target.read_text(encoding="utf-8") == '{"keep":true}'
    store.close()


def test_prune_rolls_back_failed_batch_without_partial_deletion(tmp_path: Path) -> None:
    evaluation = datetime(2026, 9, 12, 12, tzinfo=UTC)
    store = make_store(tmp_path / "outbox.sqlite3")
    first = event(FIRST_ID, "process.resource_usage")
    second = event(SECOND_ID, "process.resource_usage")
    store.enqueue([first, second])
    store.acknowledge([first.id, second.id])
    expired_at = (evaluation - timedelta(days=2)).isoformat()
    store._connection.execute("UPDATE local_events SET recorded_at = ?", (expired_at,))
    store._connection.execute(
        "CREATE TRIGGER reject_prune BEFORE DELETE ON local_events "
        f"WHEN OLD.event_id = '{SECOND_ID}' BEGIN SELECT RAISE(ABORT, 'test'); END"
    )
    store._connection.commit()

    with pytest.raises(LocalStoreError, match="prune failed"):
        store.prune(evaluation, batch_size=2)

    assert store.delivery_state(first.id) is DeliveryState.ACKED
    assert store.delivery_state(second.id) is DeliveryState.ACKED
    store.close()
