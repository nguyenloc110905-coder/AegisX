from datetime import UTC, datetime

import pytest

from aegisx_api.maintenance.cli import run_command
from aegisx_api.maintenance.types import (
    DataStatus,
    EventTypeStats,
    PruneReport,
    PruneResult,
    PruneRuleReport,
)


class FakeRetentionService:
    def __init__(self) -> None:
        self.calls: list[str] = []
        now = datetime(2026, 9, 11, tzinfo=UTC)
        self.status = DataStatus(
            policy_version=1,
            database_size_bytes=1024,
            event_count=10,
            detection_count=2,
            candidate_count=1,
            incident_count=1,
            protected_event_count=2,
            event_types=(EventTypeStats("system.status", 10, now, now),),
        )
        self.report = PruneReport(
            policy_version=1,
            evaluation_time=now,
            rules=(PruneRuleReport("system.status", now, 5, 2, 3, 0),),
        )
        self.result = PruneResult(1, now, 3, 0, True)

    async def data_status(self) -> DataStatus:
        self.calls.append("status")
        return self.status

    async def dry_run(self, _evaluation_time: datetime) -> PruneReport:
        self.calls.append("dry-run")
        return self.report

    async def prune(self, _evaluation_time: datetime) -> PruneResult:
        self.calls.append("prune")
        return self.result


@pytest.mark.asyncio
async def test_data_status_renders_only_aggregate_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    service = FakeRetentionService()

    assert await run_command(["data-status"], service) == 0

    output = capsys.readouterr().out
    assert service.calls == ["status"]
    assert "events=10" in output
    assert "system.status" in output
    assert "payload" not in output
    assert "token" not in output


@pytest.mark.asyncio
async def test_prune_dry_run_never_calls_prune(capsys: pytest.CaptureFixture[str]) -> None:
    service = FakeRetentionService()

    assert await run_command(["prune", "--dry-run"], service) == 0

    assert service.calls == ["dry-run"]
    assert "deletable_events=3" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_prune_apply_requires_confirmation(capsys: pytest.CaptureFixture[str]) -> None:
    service = FakeRetentionService()

    assert await run_command(["prune", "--apply"], service) == 2

    assert service.calls == []
    assert "requires --yes" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_confirmed_prune_apply_runs_once(capsys: pytest.CaptureFixture[str]) -> None:
    service = FakeRetentionService()

    assert await run_command(["prune", "--apply", "--yes"], service) == 0

    assert service.calls == ["prune"]
    assert "deleted_events=3" in capsys.readouterr().out
