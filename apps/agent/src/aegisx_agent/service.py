import asyncio
from collections.abc import Awaitable, Callable

import structlog

from aegisx_agent.config import AgentSettings
from aegisx_agent.runner import RunResult, collect_once

logger = structlog.get_logger(__name__)


async def run_periodically(
    settings: AgentSettings,
    collect: Callable[[AgentSettings], Awaitable[RunResult]] = collect_once,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    max_cycles: int | None = None,
) -> None:
    backoff = settings.collection_interval_seconds
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        result = await collect(settings)
        cycles += 1
        logger.info("telemetry_cycle", **result.model_dump())
        if result.delivery_status == "deferred":
            backoff = min(settings.max_backoff_seconds, backoff * 2)
        else:
            backoff = settings.collection_interval_seconds
        if max_cycles is None or cycles < max_cycles:
            await sleep(backoff)
