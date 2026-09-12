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
)

SCHEMA_VERSION = 2


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
        self._max_events = max_events
        self._max_payload_bytes = max_payload_bytes
        self._clock = clock
        self._prepare_path(path)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        try:
            os.chmod(path, 0o600)
            self._configure()
            self._validate_and_migrate()
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
            now = self._next_recorded_at()
            if "pending_events" in tables:
                rows = self._connection.execute(
                    "SELECT event_id, payload FROM pending_events ORDER BY sequence"
                ).fetchall()
                self._import_legacy(rows, DeliveryState.PENDING, None, now)
            if "quarantined_events" in tables:
                rows = self._connection.execute(
                    "SELECT event_id, payload, reason FROM quarantined_events ORDER BY sequence"
                ).fetchall()
                self._import_legacy_quarantine(rows, now)
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
            recorded_at = self._next_recorded_at()
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
            if current_bytes + new_bytes > self._max_payload_bytes:
                raise LocalStoreCapacityError("local telemetry payload limit reached")
            inserted = False
            for event in events:
                inserted = (
                    self._insert_event(event, DeliveryState.PENDING, None, recorded_at) or inserted
                )
            if inserted:
                self._record_timestamp(recorded_at)
            self._connection.commit()
            return 0
        except Exception:
            self._connection.rollback()
            raise

    def peek(self, limit: int) -> list[NormalizedEvent]:
        rows = self._connection.execute(
            "SELECT payload FROM local_events WHERE delivery_state = 'PENDING' "
            "ORDER BY sequence LIMIT ?",
            (limit,),
        ).fetchall()
        return [NormalizedEvent.model_validate_json(row[0]) for row in rows]

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
            self._connection.execute(
                f"UPDATE local_events SET delivery_state = 'QUARANTINED', "  # noqa: S608
                f"quarantine_reason = ? WHERE delivery_state = 'PENDING' "
                f"AND event_id IN ({placeholders})",
                (reason, *event_ids),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

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
