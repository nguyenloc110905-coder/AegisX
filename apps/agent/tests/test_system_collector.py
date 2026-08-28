from datetime import UTC, datetime
from uuid import UUID

from aegisx_agent.collectors.system import SystemCollector
from aegisx_agent.events import normalize_observation


def test_system_collector_returns_real_linux_status() -> None:
    observation = SystemCollector().collect()

    assert observation.event_type == "system.status"
    assert observation.data["hostname"]
    assert observation.data["os"] == "Linux"
    assert observation.data["kernel"]
    assert observation.data["uptime_seconds"] >= 0
    assert observation.data["cpu_count"] > 0
    assert observation.data["memory_total_bytes"] > 0


def test_normalization_creates_api_compatible_envelope() -> None:
    observation = SystemCollector().collect()

    event = normalize_observation(observation)

    assert UUID(event.id)
    assert event.schema_version == 1
    assert event.timestamp.tzinfo == UTC
    assert event.timestamp <= datetime.now(UTC)
    assert event.event_type == "system.status"
