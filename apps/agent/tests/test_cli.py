from datetime import UTC, datetime
from pathlib import Path

import pytest

from aegisx_agent.cli import run_command
from aegisx_agent.config import AgentSettings
from aegisx_agent.events import NormalizedEvent
from aegisx_agent.local_store import LocalTelemetryStore


def _settings(path: Path) -> AgentSettings:
    return AgentSettings(_env_file=None, state_directory=path)


def _event() -> NormalizedEvent:
    return NormalizedEvent(
        id="00000000-0000-0000-0000-000000000001",
        timestamp=datetime(2026, 9, 12, tzinfo=UTC),
        event_type="system.status",
        source="test",
        severity_hint="normal",
        data={"hostname": "private-host", "token": "secret-token"},
        metadata={},
    )


def test_local_data_status_renders_aggregate_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path)
    store = LocalTelemetryStore(
        tmp_path / "outbox.sqlite3",
        max_events=100,
        max_payload_bytes=1024 * 1024,
    )
    store.enqueue([_event()])
    store.close()

    assert run_command(["local-data-status"], settings=settings) == 0

    output = capsys.readouterr().out
    assert "event_count=1" in output
    assert "event_type=system.status" in output
    assert "private-host" not in output
    assert "secret-token" not in output


def test_local_verify_returns_distinct_exit_code_for_checksum_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path)
    store = LocalTelemetryStore(
        tmp_path / "outbox.sqlite3",
        max_events=100,
        max_payload_bytes=1024 * 1024,
    )
    store.enqueue([_event()])
    store._connection.execute("UPDATE local_events SET payload_hash = ?", ("0" * 64,))
    store._connection.commit()
    store.close()

    assert run_command(["local-verify"], settings=settings) == 1
    output = capsys.readouterr().out
    assert "valid=false" in output
    assert "failure_category=payload_hash_mismatch" in output
    assert "private-host" not in output


class FakeMaintenanceStore:
    def __init__(self) -> None:
        self.dry_runs = 0
        self.prunes = 0
        self.closed = 0

    def dry_run(self, evaluation_time: datetime):
        from aegisx_agent.local_types import LocalPruneReport

        self.dry_runs += 1
        return LocalPruneReport(1, evaluation_time, ())

    def prune(self, evaluation_time: datetime):
        from aegisx_agent.local_types import LocalPruneResult

        self.prunes += 1
        return LocalPruneResult(1, evaluation_time, 2, 200, True)

    def close(self) -> None:
        self.closed += 1


def test_local_prune_dry_run_cannot_delete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeMaintenanceStore()

    assert (
        run_command(
            ["local-prune", "--dry-run"],
            settings=_settings(tmp_path),
            store_factory=lambda *_args: fake,
        )
        == 0
    )
    assert fake.dry_runs == 1
    assert fake.prunes == 0
    assert fake.closed == 1
    assert "mode=dry-run" in capsys.readouterr().out


def test_local_prune_apply_requires_yes_before_opening_store(tmp_path: Path) -> None:
    opened = False

    def factory(*_args):
        nonlocal opened
        opened = True
        return FakeMaintenanceStore()

    assert (
        run_command(
            ["local-prune", "--apply"],
            settings=_settings(tmp_path),
            store_factory=factory,
        )
        == 2
    )
    assert opened is False


def test_local_prune_confirmed_apply_calls_prune_once(tmp_path: Path) -> None:
    fake = FakeMaintenanceStore()

    assert (
        run_command(
            ["local-prune", "--apply", "--yes"],
            settings=_settings(tmp_path),
            store_factory=lambda *_args: fake,
        )
        == 0
    )
    assert fake.dry_runs == 0
    assert fake.prunes == 1
    assert fake.closed == 1
