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


def test_local_telemetry_quota_defaults_to_256_mib() -> None:
    settings = AgentSettings(_env_file=None)

    assert settings.local_telemetry_max_bytes == 256 * 1024 * 1024


@pytest.mark.parametrize("value", [64 * 1024 * 1024, 10 * 1024 * 1024 * 1024])
def test_local_telemetry_quota_accepts_documented_boundaries(
    value: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AEGISX_LOCAL_TELEMETRY_MAX_BYTES", str(value))

    assert AgentSettings(_env_file=None).local_telemetry_max_bytes == value


@pytest.mark.parametrize("value", [64 * 1024 * 1024 - 1, 10 * 1024 * 1024 * 1024 + 1])
def test_local_telemetry_quota_rejects_values_outside_boundaries(
    value: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AEGISX_LOCAL_TELEMETRY_MAX_BYTES", str(value))

    with pytest.raises(ValueError):
        AgentSettings(_env_file=None)
