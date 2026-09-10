from datetime import UTC, datetime
from uuid import uuid4

import pytest

from aegisx_api.console.app import AegisXConsole
from aegisx_api.console.types import (
    CandidateRow,
    DashboardCounts,
    DashboardSnapshot,
    DetectionRow,
    DeviceRow,
    EventRow,
    IncidentRow,
)


def snapshot() -> DashboardSnapshot:
    now = datetime.now(UTC)
    return DashboardSnapshot(
        counts=DashboardCounts(1, 1, 1, 1, 1),
        devices=(
            DeviceRow(
                uuid4(),
                "workstation",
                "Linux",
                "Fedora",
                "6.12",
                "x86_64",
                "enabled",
                "recent",
                now,
            ),
        ),
        events=(
            EventRow(
                uuid4(),
                now,
                "process.started",
                42,
                "/usr/bin/python",
                None,
                None,
                None,
                None,
                "normal",
            ),
        ),
        detections=(
            DetectionRow(
                uuid4(), now, "PROCESS_STARTED", "informational", 0, "Verified process start."
            ),
        ),
        candidates=(
            CandidateRow(uuid4(), now, "PROCESS_LISTENER_ACTIVITY", "low", 5, "Observed activity."),
        ),
        incidents=(
            IncidentRow(
                uuid4(), now, "Test incident", "medium", 40, "OPEN", "medium", "UNDETERMINED"
            ),
        ),
    )


@pytest.mark.asyncio
async def test_console_mounts_and_populates_all_real_object_tables() -> None:
    calls = 0

    async def load() -> DashboardSnapshot:
        nonlocal calls
        calls += 1
        return snapshot()

    app = AegisXConsole(load)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#tbl-devices").row_count == 1
        assert app.query_one("#tbl-events").row_count == 1
        assert app.query_one("#tbl-detections").row_count == 1
        assert app.query_one("#tbl-candidates").row_count == 1
        assert app.query_one("#tbl-incidents").row_count == 1
        device_columns = [
            str(column.label) for column in app.query_one("#tbl-devices").columns.values()
        ]
        assert "Enrollment" in device_columns
        assert "Telemetry" in device_columns
        assert "Last seen" in device_columns
        assert "Active" not in device_columns
        assert str(app.query_one("#coverage-panel").render()) == (
            "Polling telemetry only; AegisX does not prevent attacks and may miss activity "
            "between snapshots."
        )
        assert "rule matches are not automatic alerts" in str(app.query_one("#log-panel").render())
        await pilot.press("r")
        await pilot.pause()

    assert calls == 2


@pytest.mark.asyncio
async def test_console_bounds_loader_failure_without_exposing_exception_text() -> None:
    async def fail() -> DashboardSnapshot:
        raise RuntimeError("password=must-not-leak")

    app = AegisXConsole(fail)
    async with app.run_test() as pilot:
        await pilot.pause()
        log_text = str(app.query_one("#log-panel").render())

    assert "Unable to load dashboard data" in log_text
    assert "must-not-leak" not in log_text
