import os
import sqlite3
from pathlib import Path

from aegisx_agent.events import NormalizedEvent


class Outbox:
    def __init__(self, path: Path, max_events: int) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._connection = sqlite3.connect(path)
        os.chmod(path, 0o600)
        self._max_events = max_events
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS quarantined_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                reason TEXT NOT NULL,
                quarantined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._connection.commit()

    def enqueue(self, events: list[NormalizedEvent]) -> int:
        self._connection.executemany(
            "INSERT OR IGNORE INTO pending_events (event_id, payload) VALUES (?, ?)",
            [(event.id, event.model_dump_json()) for event in events],
        )
        excess = max(0, self.count() - self._max_events)
        if excess:
            self._connection.execute(
                """
                DELETE FROM pending_events
                WHERE sequence IN (
                    SELECT sequence FROM pending_events ORDER BY sequence LIMIT ?
                )
                """,
                (excess,),
            )
        self._connection.commit()
        return excess

    def peek(self, limit: int) -> list[NormalizedEvent]:
        rows = self._connection.execute(
            "SELECT payload FROM pending_events ORDER BY sequence LIMIT ?",
            (limit,),
        ).fetchall()
        return [NormalizedEvent.model_validate_json(row[0]) for row in rows]

    def acknowledge(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        placeholders = ",".join("?" for _ in event_ids)
        self._connection.execute(
            f"DELETE FROM pending_events WHERE event_id IN ({placeholders})",  # noqa: S608
            event_ids,
        )
        self._connection.commit()

    def quarantine(self, event_ids: list[str], reason: str) -> None:
        if not event_ids:
            return
        placeholders = ",".join("?" for _ in event_ids)
        rows = self._connection.execute(
            f"SELECT event_id, payload FROM pending_events WHERE event_id IN ({placeholders})",  # noqa: S608
            event_ids,
        ).fetchall()
        self._connection.executemany(
            """
            INSERT OR REPLACE INTO quarantined_events (event_id, payload, reason)
            VALUES (?, ?, ?)
            """,
            [(row[0], row[1], reason) for row in rows],
        )
        self._connection.execute(
            f"DELETE FROM pending_events WHERE event_id IN ({placeholders})",  # noqa: S608
            event_ids,
        )
        excess = max(0, self.quarantine_count() - self._max_events)
        if excess:
            self._connection.execute(
                """
                DELETE FROM quarantined_events
                WHERE sequence IN (
                    SELECT sequence FROM quarantined_events ORDER BY sequence LIMIT ?
                )
                """,
                (excess,),
            )
        self._connection.commit()

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

    def close(self) -> None:
        self._connection.close()
