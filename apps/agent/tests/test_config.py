import pytest

from aegisx_agent.config import AgentSettings


def test_high_volume_observations_are_disabled_by_default() -> None:
    settings = AgentSettings(_env_file=None)

    assert settings.emit_process_resource_usage is False
    assert settings.emit_network_snapshot_observations is False


def test_high_volume_observations_can_be_enabled_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AEGISX_EMIT_PROCESS_RESOURCE_USAGE", "true")
    monkeypatch.setenv("AEGISX_EMIT_NETWORK_SNAPSHOT_OBSERVATIONS", "true")

    settings = AgentSettings(_env_file=None)

    assert settings.emit_process_resource_usage is True
    assert settings.emit_network_snapshot_observations is True
