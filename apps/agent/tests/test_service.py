import pytest

from aegisx_agent.config import AgentSettings
from aegisx_agent.runner import RunResult
from aegisx_agent.service import run_periodically


@pytest.mark.asyncio
async def test_periodic_runner_backs_off_and_resets_after_recovery(tmp_path) -> None:
    results = iter(
        [
            RunResult(
                accepted=0,
                duplicates=0,
                queued=1,
                evicted=0,
                quarantined=0,
                delivery_status="deferred",
            ),
            RunResult(
                accepted=0,
                duplicates=0,
                queued=2,
                evicted=0,
                quarantined=0,
                delivery_status="deferred",
            ),
            RunResult(
                accepted=3,
                duplicates=0,
                queued=0,
                evicted=0,
                quarantined=0,
                delivery_status="delivered",
            ),
        ]
    )
    delays: list[float] = []

    async def collect(settings: AgentSettings) -> RunResult:
        return next(results)

    async def sleep(delay: float) -> None:
        delays.append(delay)

    settings = AgentSettings(
        _env_file=None,
        state_directory=tmp_path,
        collection_interval_seconds=10,
        max_backoff_seconds=60,
    )

    await run_periodically(settings, collect=collect, sleep=sleep, max_cycles=3)

    assert delays == [20, 40]
