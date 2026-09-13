import json
import os
import sqlite3
import stat
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from aegisx_agent.events import NormalizedEvent
from aegisx_agent.local_policy import (
    LOCAL_POLICY_VERSION,
    DeliveryState,
    calculate_payload_hash,
    canonical_event_json,
    classify_event,
    retention_for,
)
from aegisx_agent.local_types import (
    CoverageGapCategory,
    EventPriority,
    LocalDataStatus,
    LocalEventTypeStats,
    LocalPruneReport,
    LocalPruneResult,
    LocalPruneRuleReport,
    LocalVerifyResult,
)

SCHEMA_VERSION = 2
MAX_COVERAGE_GAPS = 1000

_GAP_REASONS = {
    CoverageGapCategory.STORAGE_LIMIT: "local telemetry storage limit reached",
    CoverageGapCategory.STORAGE_WRITE_FAILURE: "local telemetry storage write failed",
    CoverageGapCategory.CLOCK_REGRESSION: "local clock moved backwards",
    CoverageGapCategory.LEGACY_MIGRATION_FAILURE: "legacy outbox migration failed",
}


class LocalStoreError(RuntimeError):
    """Base class for bounded local telemetry storage failures."""


class LocalStorePathError(LocalStoreError):
    """Raised when the SQLite target is unsafe."""


class LocalStoreIntegrityError(LocalStoreError):
    """Raised when immutable Event identity or content conflicts."""


class LocalStoreCapacityError(LocalStoreError):
    """Raised rather than silently deleting protected local evidence."""


class LocalStoreMigrationError(LocalStoreError):
    """Raised when a schema cannot be upgraded without evidence loss."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class LocalTelemetryStore:
    def __init__(
        self,
        path: Path,
        max_events: int,
        max_payload_bytes: int,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if max_events < 1 or max_payload_bytes < 1:
            raise ValueError("local telemetry bounds must be positive")
        self._path = path
        self._gap_sidecar = path.with_name("coverage-gap.json")
        self._max_events = max_events
        self._max_payload_bytes = max_payload_bytes
        self._clock = clock
        self._prepare_path(path)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        try:
            os.chmod(path, 0o600)
            self._configure()
            self._validate_and_migrate()
            self._import_gap_sidecar()
        except Exception:
            self._connection.close()
            raise

    @staticmethod
    def _prepare_path(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        try:
            details = path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(details.st_mode):
            raise LocalStorePathError("local telemetry database must not be a symlink")
        if not stat.S_ISREG(details.st_mode):
            raise LocalStorePathError("local telemetry database must be a regular file")
        if details.st_uid != os.getuid():
            raise LocalStorePathError("local telemetry database must belong to the current user")

    def _configure(self) -> None:
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")

    def _validate_and_migrate(self) -> None:
        quick_check = self._connection.execute("PRAGMA quick_check").fetchone()
        if quick_check != ("ok",):
            raise LocalStoreIntegrityError("local telemetry database failed integrity check")
        version_row = self._connection.execute("PRAGMA user_version").fetchone()
        version = int(version_row[0]) if version_row else 0
        if version > SCHEMA_VERSION:
            raise LocalStoreMigrationError(
                f"local telemetry database has newer schema version {version}"
            )
        if version == SCHEMA_VERSION:
            return
        if version != 0:
            raise LocalStoreMigrationError(f"unsupported local telemetry schema version {version}")
        self._migrate_v0()

    def _migrate_v0(self) -> None:
        try:
            self._connection.execute("BEGIN EXCLUSIVE")
            self._create_schema_v2()
            tables = self._table_names()
            pending_rows: list[tuple[object, ...]] = []
            quarantine_rows: list[tuple[object, ...]] = []
            if "pending_events" in tables:
                pending_rows = self._connection.execute(
                    "SELECT event_id, payload FROM pending_events ORDER BY sequence"
                ).fetchall()
            if "quarantined_events" in tables:
                quarantine_rows = self._connection.execute(
                    "SELECT event_id, payload, reason FROM quarantined_events ORDER BY sequence"
                ).fetchall()
            if pending_rows or quarantine_rows:
                legacy_ids = [str(row[0]) for row in (*pending_rows, *quarantine_rows)]
                if len(legacy_ids) != len(set(legacy_ids)):
                    raise ValueError("legacy event UUID occurs in multiple delivery states")
                now = self._next_recorded_at()
                self._import_legacy(pending_rows, DeliveryState.PENDING, None, now)
                self._import_legacy_quarantine(quarantine_rows, now)
            if "pending_events" in tables:
                self._connection.execute("DROP TABLE pending_events")
            if "quarantined_events" in tables:
                self._connection.execute("DROP TABLE quarantined_events")
            self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._connection.commit()
        except (sqlite3.Error, ValidationError, ValueError) as error:
            self._connection.rollback()
            raise LocalStoreMigrationError("legacy migration failed") from error

    def _create_schema_v2(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE local_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                schema_version INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                event_timestamp TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                priority TEXT NOT NULL CHECK (
                    priority IN ('BULK', 'OPERATIONAL', 'SECURITY', 'UNCLASSIFIED')
                ),
                payload TEXT NOT NULL,
                payload_bytes INTEGER NOT NULL CHECK (payload_bytes >= 0),
                payload_hash TEXT NOT NULL,
                delivery_state TEXT NOT NULL CHECK (
                    delivery_state IN ('PENDING', 'ACKED', 'QUARANTINED')
                ),
                acknowledged_at TEXT,
                quarantine_reason TEXT,
                CHECK (
                    (delivery_state = 'PENDING' AND acknowledged_at IS NULL
                        AND quarantine_reason IS NULL)
                    OR (delivery_state = 'ACKED' AND acknowledged_at IS NOT NULL
                        AND quarantine_reason IS NULL)
                    OR (delivery_state = 'QUARANTINED' AND acknowledged_at IS NULL
                        AND quarantine_reason IS NOT NULL)
                )
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX ix_local_events_delivery_sequence "
            "ON local_events (delivery_state, sequence)"
        )
        self._connection.execute(
            "CREATE INDEX ix_local_events_type_recorded ON local_events (event_type, recorded_at)"
        )
        self._connection.execute(
            "CREATE INDEX ix_local_events_priority_recorded ON local_events (priority, recorded_at)"
        )
        self._connection.execute(
            """
            CREATE TABLE coverage_gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                category TEXT NOT NULL,
                reason TEXT NOT NULL,
                dropped_event_count INTEGER NOT NULL CHECK (dropped_event_count >= 0)
            )
            """
        )
        self._connection.execute(
            "CREATE TABLE local_store_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self._connection.executemany(
            "INSERT INTO local_store_metadata (key, value) VALUES (?, ?)",
            [("policy_version", str(LOCAL_POLICY_VERSION)), ("legacy_migration", "complete")],
        )

    def _table_names(self) -> set[str]:
        return {
            str(row[0])
            for row in self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    def _next_recorded_at(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("local telemetry clock must return a timezone-aware datetime")
        now = now.astimezone(UTC)
        row = self._connection.execute(
            "SELECT value FROM local_store_metadata WHERE key = 'last_recorded_at'"
        ).fetchone()
        if row is not None:
            previous = datetime.fromisoformat(str(row[0]))
            now = max(now, previous)
        return now

    def _record_timestamp(self, recorded_at: datetime) -> None:
        self._connection.execute(
            "INSERT INTO local_store_metadata (key, value) VALUES ('last_recorded_at', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (recorded_at.isoformat(),),
        )

    @staticmethod
    def _require_aware(value: datetime, field: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field} must be timezone-aware")

    def _record_gap(
        self,
        category: CoverageGapCategory,
        recorded_at: datetime,
        dropped_event_count: int,
        *,
        closed: bool = False,
    ) -> None:
        existing = self._connection.execute(
            "SELECT id FROM coverage_gaps WHERE category = ? AND ended_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (category.value,),
        ).fetchone()
        if existing is not None and not closed:
            self._connection.execute(
                "UPDATE coverage_gaps SET dropped_event_count = dropped_event_count + ? "
                "WHERE id = ?",
                (dropped_event_count, existing[0]),
            )
        else:
            self._connection.execute(
                "INSERT INTO coverage_gaps "
                "(started_at, ended_at, category, reason, dropped_event_count) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    recorded_at.isoformat(),
                    recorded_at.isoformat() if closed else None,
                    category.value,
                    _GAP_REASONS[category],
                    dropped_event_count,
                ),
            )
        excess = (
            int(self._connection.execute("SELECT COUNT(*) FROM coverage_gaps").fetchone()[0])
            - MAX_COVERAGE_GAPS
        )
        if excess > 0:
            self._connection.execute(
                "DELETE FROM coverage_gaps WHERE id IN ("
                "SELECT id FROM coverage_gaps WHERE ended_at IS NOT NULL "
                "ORDER BY id LIMIT ?)",
                (excess,),
            )

    def _close_storage_gaps(self, recorded_at: datetime) -> None:
        self._connection.execute(
            "UPDATE coverage_gaps SET ended_at = ? WHERE ended_at IS NULL AND category IN (?, ?)",
            (
                recorded_at.isoformat(),
                CoverageGapCategory.STORAGE_LIMIT.value,
                CoverageGapCategory.STORAGE_WRITE_FAILURE.value,
            ),
        )

    def _write_gap_sidecar(
        self,
        category: CoverageGapCategory,
        recorded_at: datetime,
        dropped_event_count: int,
    ) -> None:
        try:
            details = self._gap_sidecar.lstat()
        except FileNotFoundError:
            details = None
        if details is not None:
            if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
                raise LocalStorePathError("coverage gap sidecar must be a regular file")
            if details.st_uid != os.getuid() or details.st_size > 4096:
                raise LocalStorePathError("coverage gap sidecar is unsafe")
            try:
                existing = json.loads(self._gap_sidecar.read_text(encoding="utf-8"))
                existing_category = CoverageGapCategory(str(existing["category"]))
                existing_count = int(existing["dropped_event_count"])
                existing_started_at = datetime.fromisoformat(str(existing["started_at"]))
                self._require_aware(existing_started_at, "coverage gap started_at")
                if existing_count < 0:
                    raise ValueError("negative dropped event count")
                if existing_category is category:
                    dropped_event_count += existing_count
                    recorded_at = min(recorded_at, existing_started_at)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise LocalStoreIntegrityError("coverage gap sidecar is invalid") from error
        payload = {
            "category": category.value,
            "dropped_event_count": dropped_event_count,
            "started_at": recorded_at.isoformat(),
        }
        temporary = self._gap_sidecar.with_name(f".{self._gap_sidecar.name}.tmp")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._gap_sidecar)
            os.chmod(self._gap_sidecar, 0o600)
            directory = os.open(self._gap_sidecar.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except Exception:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise

    def _import_gap_sidecar(self) -> None:
        try:
            details = self._gap_sidecar.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode):
            raise LocalStorePathError("coverage gap sidecar must be a regular file")
        if details.st_uid != os.getuid() or details.st_size > 4096:
            raise LocalStorePathError("coverage gap sidecar is unsafe")
        try:
            raw = json.loads(self._gap_sidecar.read_text(encoding="utf-8"))
            category = CoverageGapCategory(str(raw["category"]))
            recorded_at = datetime.fromisoformat(str(raw["started_at"]))
            dropped_event_count = int(raw["dropped_event_count"])
            self._require_aware(recorded_at, "coverage gap started_at")
            recorded_at = recorded_at.astimezone(UTC)
            if dropped_event_count < 0:
                raise ValueError("negative dropped event count")
            self._connection.execute("BEGIN IMMEDIATE")
            self._record_gap(category, recorded_at, dropped_event_count)
            self._connection.commit()
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, sqlite3.Error) as error:
            self._connection.rollback()
            raise LocalStoreIntegrityError("coverage gap sidecar is invalid") from error
        self._gap_sidecar.unlink()
        directory = os.open(self._gap_sidecar.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def _prune_expired_for_space(self, evaluation_time: datetime, bytes_needed: int) -> int:
        freed = 0
        for priority in (
            EventPriority.BULK,
            EventPriority.OPERATIONAL,
            EventPriority.SECURITY,
        ):
            retention = retention_for(priority)
            if retention is None:
                continue
            cutoff = evaluation_time - retention
            rows = self._connection.execute(
                "SELECT sequence, payload_bytes FROM local_events "
                "WHERE priority = ? AND delivery_state = 'ACKED' AND recorded_at <= ? "
                "ORDER BY recorded_at, sequence",
                (priority.value, cutoff.isoformat()),
            ).fetchall()
            selected: list[int] = []
            for sequence, payload_bytes in rows:
                selected.append(int(sequence))
                freed += int(payload_bytes)
                if freed >= bytes_needed:
                    break
            if selected:
                placeholders = ",".join("?" for _ in selected)
                self._connection.execute(
                    f"DELETE FROM local_events WHERE sequence IN ({placeholders})",  # noqa: S608
                    selected,
                )
            if freed >= bytes_needed:
                break
        return freed

    def _insert_event(
        self,
        event: NormalizedEvent,
        state: DeliveryState,
        reason: str | None,
        recorded_at: datetime,
    ) -> bool:
        payload = canonical_event_json(event)
        existing = self._connection.execute(
            "SELECT payload FROM local_events WHERE event_id = ?", (event.id,)
        ).fetchone()
        if existing is not None:
            if existing[0] != payload:
                raise LocalStoreIntegrityError("event UUID maps to conflicting immutable payload")
            return False
        payload_bytes = len(payload.encode("utf-8"))
        self._connection.execute(
            """
            INSERT INTO local_events (
                event_id, schema_version, event_type, event_timestamp, recorded_at,
                priority, payload, payload_bytes, payload_hash, delivery_state,
                acknowledged_at, quarantine_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                event.id,
                event.schema_version,
                event.event_type,
                event.timestamp.isoformat(),
                recorded_at.isoformat(),
                classify_event(event.event_type).value,
                payload,
                payload_bytes,
                calculate_payload_hash(payload),
                state.value,
                reason,
            ),
        )
        return True

    def _import_legacy(
        self,
        rows: list[tuple[object, ...]],
        state: DeliveryState,
        reason: str | None,
        recorded_at: datetime,
    ) -> None:
        for row in rows:
            event = NormalizedEvent.model_validate_json(str(row[1]))
            if event.id != str(row[0]):
                raise ValueError("legacy event UUID does not match payload")
            self._insert_event(event, state, reason, recorded_at)
        if rows:
            self._record_timestamp(recorded_at)

    def _import_legacy_quarantine(
        self, rows: list[tuple[object, ...]], recorded_at: datetime
    ) -> None:
        for row in rows:
            event = NormalizedEvent.model_validate_json(str(row[1]))
            if event.id != str(row[0]):
                raise ValueError("legacy event UUID does not match payload")
            self._insert_event(event, DeliveryState.QUARANTINED, str(row[2]), recorded_at)
        if rows:
            self._record_timestamp(recorded_at)

    def enqueue(self, events: list[NormalizedEvent]) -> int:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            clock_time = self._clock()
            self._require_aware(clock_time, "local telemetry clock")
            clock_time = clock_time.astimezone(UTC)
            previous_row = self._connection.execute(
                "SELECT value FROM local_store_metadata WHERE key = 'last_recorded_at'"
            ).fetchone()
            previous = datetime.fromisoformat(str(previous_row[0])) if previous_row else None
            recorded_at = max(clock_time, previous) if previous is not None else clock_time
            if previous is not None and clock_time < previous:
                self._record_gap(
                    CoverageGapCategory.CLOCK_REGRESSION,
                    recorded_at,
                    0,
                    closed=True,
                )
            unique_new = {event.id: event for event in events}
            backlog = self.count() + self.quarantine_count()
            existing_ids = (
                {
                    str(row[0])
                    for row in self._connection.execute(
                        "SELECT event_id FROM local_events WHERE event_id IN ({})".format(  # noqa: S608
                            ",".join("?" for _ in unique_new)
                        ),
                        tuple(unique_new),
                    ).fetchall()
                }
                if unique_new
                else set()
            )
            if backlog + len(unique_new.keys() - existing_ids) > self._max_events:
                self._record_gap(
                    CoverageGapCategory.STORAGE_LIMIT,
                    recorded_at,
                    len(unique_new.keys() - existing_ids),
                )
                self._connection.commit()
                raise LocalStoreCapacityError("local delivery backlog limit reached")
            current_bytes = int(
                self._connection.execute(
                    "SELECT COALESCE(SUM(payload_bytes), 0) FROM local_events"
                ).fetchone()[0]
            )
            new_bytes = sum(
                len(canonical_event_json(item).encode("utf-8"))
                for event_id, item in unique_new.items()
                if event_id not in existing_ids
            )
            overflow = current_bytes + new_bytes - self._max_payload_bytes
            if overflow > 0:
                freed = self._prune_expired_for_space(recorded_at, overflow)
                current_bytes -= freed
            if current_bytes + new_bytes > self._max_payload_bytes:
                self._record_gap(
                    CoverageGapCategory.STORAGE_LIMIT,
                    recorded_at,
                    len(unique_new.keys() - existing_ids),
                )
                self._connection.commit()
                raise LocalStoreCapacityError("local telemetry payload limit reached")
            inserted = False
            for event in events:
                inserted = (
                    self._insert_event(event, DeliveryState.PENDING, None, recorded_at) or inserted
                )
            if inserted:
                self._record_timestamp(recorded_at)
                self._close_storage_gaps(recorded_at)
            self._connection.commit()
            return 0
        except LocalStoreCapacityError:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise
        except sqlite3.Error as error:
            self._connection.rollback()
            try:
                clock_time = self._clock()
                self._require_aware(clock_time, "local telemetry clock")
                clock_time = clock_time.astimezone(UTC)
                self._write_gap_sidecar(
                    CoverageGapCategory.STORAGE_WRITE_FAILURE,
                    clock_time,
                    len({event.id for event in events}),
                )
            except (OSError, ValueError):
                pass
            raise LocalStoreError("local telemetry write failed") from error
        except Exception:
            self._connection.rollback()
            raise

    def data_status(self) -> LocalDataStatus:
        rows = self._connection.execute(
            "SELECT event_type, COUNT(*), COALESCE(SUM(payload_bytes), 0), "
            "MIN(recorded_at), MAX(recorded_at) FROM local_events "
            "GROUP BY event_type ORDER BY event_type"
        ).fetchall()
        event_types = tuple(
            LocalEventTypeStats(
                event_type=str(row[0]),
                count=int(row[1]),
                payload_bytes=int(row[2]),
                oldest_recorded_at=datetime.fromisoformat(str(row[3])),
                newest_recorded_at=datetime.fromisoformat(str(row[4])),
            )
            for row in rows
        )
        counts = {
            str(row[0]): int(row[1])
            for row in self._connection.execute(
                "SELECT delivery_state, COUNT(*) FROM local_events GROUP BY delivery_state"
            ).fetchall()
        }
        return LocalDataStatus(
            policy_version=LOCAL_POLICY_VERSION,
            schema_version=SCHEMA_VERSION,
            logical_payload_bytes=sum(item.payload_bytes for item in event_types),
            database_file_bytes=self._path.stat().st_size,
            event_count=sum(item.count for item in event_types),
            pending_count=counts.get(DeliveryState.PENDING.value, 0),
            acknowledged_count=counts.get(DeliveryState.ACKED.value, 0),
            quarantined_count=counts.get(DeliveryState.QUARANTINED.value, 0),
            coverage_gap_count=int(
                self._connection.execute("SELECT COUNT(*) FROM coverage_gaps").fetchone()[0]
            ),
            event_types=event_types,
        )

    def verify(self) -> LocalVerifyResult:
        quick_check = self._connection.execute("PRAGMA quick_check").fetchone()
        if quick_check != ("ok",):
            return LocalVerifyResult(False, 0, None, "sqlite_quick_check")
        checked = 0
        rows = self._connection.execute(
            "SELECT sequence, event_id, payload, payload_bytes, payload_hash "
            "FROM local_events ORDER BY sequence"
        ).fetchall()
        for sequence, event_id, payload, payload_bytes, payload_hash in rows:
            try:
                parsed = NormalizedEvent.model_validate_json(str(payload))
            except ValidationError:
                return LocalVerifyResult(False, checked, int(sequence), "payload_parse")
            if parsed.id != str(event_id):
                return LocalVerifyResult(False, checked, int(sequence), "event_id_mismatch")
            if canonical_event_json(parsed) != str(payload):
                return LocalVerifyResult(False, checked, int(sequence), "noncanonical_payload")
            try:
                stored_payload_bytes = int(payload_bytes)
            except (TypeError, ValueError):
                return LocalVerifyResult(False, checked, int(sequence), "payload_size_mismatch")
            if len(str(payload).encode("utf-8")) != stored_payload_bytes:
                return LocalVerifyResult(False, checked, int(sequence), "payload_size_mismatch")
            if calculate_payload_hash(str(payload)) != str(payload_hash):
                return LocalVerifyResult(False, checked, int(sequence), "payload_hash_mismatch")
            checked += 1
        return LocalVerifyResult(True, checked, None, None)

    def dry_run(self, evaluation_time: datetime) -> LocalPruneReport:
        self._require_aware(evaluation_time, "evaluation_time")
        evaluation_time = evaluation_time.astimezone(UTC)
        rules: list[LocalPruneRuleReport] = []
        for priority in (
            EventPriority.BULK,
            EventPriority.OPERATIONAL,
            EventPriority.SECURITY,
        ):
            retention = retention_for(priority)
            if retention is None:
                continue
            cutoff = evaluation_time - retention
            row = self._connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(payload_bytes), 0) FROM local_events "
                "WHERE priority = ? AND delivery_state = 'ACKED' AND recorded_at <= ?",
                (priority.value, cutoff.isoformat()),
            ).fetchone()
            rules.append(
                LocalPruneRuleReport(
                    priority=priority,
                    cutoff=cutoff,
                    eligible_events=int(row[0]),
                    eligible_payload_bytes=int(row[1]),
                )
            )
        return LocalPruneReport(LOCAL_POLICY_VERSION, evaluation_time, tuple(rules))

    def prune(self, evaluation_time: datetime, batch_size: int = 1000) -> LocalPruneResult:
        self._require_aware(evaluation_time, "evaluation_time")
        evaluation_time = evaluation_time.astimezone(UTC)
        if not 1 <= batch_size <= 1000:
            raise ValueError("batch_size must be between 1 and 1000")
        deleted_events = 0
        deleted_payload_bytes = 0
        for priority in (
            EventPriority.BULK,
            EventPriority.OPERATIONAL,
            EventPriority.SECURITY,
        ):
            retention = retention_for(priority)
            if retention is None:
                continue
            cutoff = evaluation_time - retention
            while True:
                try:
                    self._connection.execute("BEGIN IMMEDIATE")
                    rows = self._connection.execute(
                        "SELECT sequence, payload_bytes FROM local_events "
                        "WHERE priority = ? AND delivery_state = 'ACKED' "
                        "AND recorded_at <= ? ORDER BY recorded_at, sequence LIMIT ?",
                        (priority.value, cutoff.isoformat(), batch_size),
                    ).fetchall()
                    if not rows:
                        self._connection.commit()
                        break
                    sequences = [int(row[0]) for row in rows]
                    placeholders = ",".join("?" for _ in sequences)
                    self._connection.execute(
                        f"DELETE FROM local_events WHERE sequence IN ({placeholders})",  # noqa: S608
                        sequences,
                    )
                    self._connection.commit()
                    deleted_events += len(rows)
                    deleted_payload_bytes += sum(int(row[1]) for row in rows)
                except sqlite3.Error as error:
                    self._connection.rollback()
                    raise LocalStoreError("local telemetry prune failed") from error
        return LocalPruneResult(
            LOCAL_POLICY_VERSION,
            evaluation_time,
            deleted_events,
            deleted_payload_bytes,
            True,
        )

    def peek(self, limit: int) -> list[NormalizedEvent]:
        rows = self._connection.execute(
            "SELECT payload FROM local_events WHERE delivery_state = 'PENDING' "
            "ORDER BY sequence LIMIT ?",
            (limit,),
        ).fetchall()
        try:
            return [NormalizedEvent.model_validate_json(row[0]) for row in rows]
        except ValidationError as error:
            raise LocalStoreIntegrityError(
                "pending local telemetry payload is malformed"
            ) from error

    def acknowledge(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        placeholders = ",".join("?" for _ in event_ids)
        acknowledged_at = self._next_recorded_at().isoformat()
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                f"UPDATE local_events SET delivery_state = 'ACKED', acknowledged_at = ? "  # noqa: S608
                f"WHERE delivery_state = 'PENDING' AND event_id IN ({placeholders})",
                (acknowledged_at, *event_ids),
            )
            self._connection.commit()
        except sqlite3.Error as error:
            self._connection.rollback()
            raise LocalStoreError("local acknowledgement update failed") from error

    def quarantine(self, event_ids: list[str], reason: str) -> None:
        if not event_ids:
            return
        if len(reason) > 64 or not reason.startswith("http_") or not reason[5:].isdigit():
            raise ValueError("quarantine reason must be a bounded HTTP category")
        placeholders = ",".join("?" for _ in event_ids)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                f"UPDATE local_events SET delivery_state = 'QUARANTINED', "  # noqa: S608
                f"quarantine_reason = ? WHERE delivery_state = 'PENDING' "
                f"AND event_id IN ({placeholders})",
                (reason, *event_ids),
            )
            self._connection.commit()
        except sqlite3.Error as error:
            self._connection.rollback()
            raise LocalStoreError("local quarantine update failed") from error

    def delivery_state(self, event_id: str) -> DeliveryState | None:
        row = self._connection.execute(
            "SELECT delivery_state FROM local_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return DeliveryState(str(row[0])) if row else None

    def count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM local_events WHERE delivery_state = 'PENDING'"
        ).fetchone()
        return int(row[0]) if row else 0

    def quarantine_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM local_events WHERE delivery_state = 'QUARANTINED'"
        ).fetchone()
        return int(row[0]) if row else 0

    def quarantine_reasons(self) -> list[str]:
        rows = self._connection.execute(
            "SELECT quarantine_reason FROM local_events "
            "WHERE delivery_state = 'QUARANTINED' ORDER BY sequence"
        ).fetchall()
        return [str(row[0]) for row in rows]

    def close(self) -> None:
        self._connection.close()
