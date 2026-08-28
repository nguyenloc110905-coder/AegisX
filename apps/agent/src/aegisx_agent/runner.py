import platform
import socket
from collections.abc import Iterable
from typing import Protocol

from aegisx_agent.api_client import AegisXClient, DeviceProfile, IngestionResult
from aegisx_agent.collectors.base import Collector
from aegisx_agent.collectors.process import ProcessCollector
from aegisx_agent.collectors.system import SystemCollector
from aegisx_agent.config import AgentSettings
from aegisx_agent.credentials import AgentCredentials, load_credentials, save_credentials
from aegisx_agent.events import NormalizedEvent, Observation, normalize_observation
from aegisx_agent.identity import load_or_create_identity


class TelemetryClient(Protocol):
    async def register(self, profile: DeviceProfile) -> AgentCredentials: ...

    async def send_events(
        self, token: str, events: list[NormalizedEvent]
    ) -> IngestionResult: ...


def _device_profile(external_id: str) -> DeviceProfile:
    os_release = platform.freedesktop_os_release()
    return DeviceProfile(
        external_id=external_id,
        name=socket.gethostname(),
        os="Linux",
        os_version=os_release.get("PRETTY_NAME", platform.release()),
        kernel=platform.release(),
        architecture=platform.machine(),
    )


def _flatten(observations: Observation | list[Observation]) -> Iterable[Observation]:
    return observations if isinstance(observations, list) else [observations]


async def collect_once(
    settings: AgentSettings,
    client: TelemetryClient | None = None,
    collectors: list[Collector] | None = None,
) -> IngestionResult:
    identity = load_or_create_identity(settings.state_directory / "identity.json")
    credentials_path = settings.state_directory / "credentials.json"
    credentials = load_credentials(credentials_path)
    owned_client = client is None
    resolved_client = client or AegisXClient(
        settings.api_url,
        timeout_seconds=settings.request_timeout_seconds,
    )
    try:
        if credentials is None:
            credentials = await resolved_client.register(_device_profile(identity.external_id))
            save_credentials(credentials_path, credentials)

        resolved_collectors = collectors or [
            SystemCollector(),
            ProcessCollector(max_processes=settings.max_processes),
        ]
        events = [
            normalize_observation(observation)
            for collector in resolved_collectors
            for observation in _flatten(collector.collect())
        ]
        accepted = 0
        duplicates = 0
        for offset in range(0, len(events), settings.batch_size):
            result = await resolved_client.send_events(
                credentials.token,
                events[offset : offset + settings.batch_size],
            )
            accepted += result.accepted
            duplicates += result.duplicates
        return IngestionResult(accepted=accepted, duplicates=duplicates)
    finally:
        if owned_client and isinstance(resolved_client, AegisXClient):
            await resolved_client.close()
