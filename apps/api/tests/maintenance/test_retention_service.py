from datetime import UTC, datetime

import pytest

from aegisx_api.maintenance.retention_service import RetentionPruneError, RetentionService
from aegisx_api.maintenance.types import (
    DataStatus,
    EventTypeStats,
    PruneReport,
    PruneRuleReport,
)


def test_status_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        DataStatus(
            policy_version=1,
            database_size_bytes=0,
            event_count=-1,
            detection_count=0,
            candidate_count=0,
            incident_count=0,
            protected_event_count=0,
            event_types=(),
        )


def test_event_stats_require_timezone_aware_bounds() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        EventTypeStats(
            event_type="system.status",
            count=1,
            oldest_ingested_at=datetime(2026, 9, 1),
            newest_ingested_at=datetime(2026, 9, 1, tzinfo=UTC),
        )


def test_prune_report_totals_are_derived_from_rules() -> None:
    now = datetime(2026, 9, 11, tzinfo=UTC)
    report = PruneReport(
        policy_version=1,
        evaluation_time=now,
        rules=(
            PruneRuleReport("system.status", now, 10, 2, 8, 0),
            PruneRuleReport("process.started", now, 5, 1, 4, 4),
        ),
    )

    assert report.expired_events == 15
    assert report.protected_events == 3
    assert report.deletable_events == 12
    assert report.deletable_detections == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("batch_size", [0, 1001])
async def test_prune_rejects_out_of_bounds_batch_size(batch_size: int) -> None:
    service = RetentionService(None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="between 1 and 1000"):
        await service.prune(datetime(2026, 9, 11, tzinfo=UTC), batch_size=batch_size)


@pytest.mark.asyncio
async def test_prune_error_reports_only_previously_committed_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = RetentionService(None)  # type: ignore[arg-type]
    calls = 0

    async def fail_second_batch(**_kwargs: object) -> tuple[int, int]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return 1, 2
        raise RuntimeError("raw database detail must not be copied")

    monkeypatch.setattr(service, "_prune_batch", fail_second_batch)

    with pytest.raises(RetentionPruneError) as caught:
        await service.prune(datetime(2026, 9, 11, tzinfo=UTC))

    assert caught.value.deleted_events == 1
    assert caught.value.deleted_detections == 2
    assert caught.value.failure_category == "RuntimeError"
    assert "raw database detail" not in str(caught.value)
