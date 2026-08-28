import platform
import socket
from collections.abc import Iterable
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel

from aegisx_agent.api_client import (
    AegisXClient,
    DeviceProfile,
    IngestionResult,
    PermanentDeliveryError,
    TransientDeliveryError,
)
from aegisx_agent.collectors.base import Collector
from aegisx_agent.collectors.network import NetworkCollector
from aegisx_agent.collectors.process import ProcessCollector
from aegisx_agent.collectors.system import SystemCollector
from aegisx_agent.config import AgentSettings
from aegisx_agent.credentials import AgentCredentials, load_credentials, save_credentials
from aegisx_agent.events import NormalizedEvent, Observation, normalize_observation
from aegisx_agent.identity import load_or_create_identity
from aegisx_agent.outbox import Outbox


class RunResult(BaseModel):
    accepted: int
    duplicates: int
    queued: int
    evicted: int
    quarantined: int
    delivery_status: Literal["delivered", "deferred"]


class TelemetryClient(Protocol):
    async def register(self, profile: DeviceProfile) -> AgentCredentials: ...

    async def send_events(self, token: str, events: list[NormalizedEvent]) -> IngestionResult: ...


async def _deliver_batch(
    client: TelemetryClient,
    token: str,
    outbox: Outbox,
    batch: list[NormalizedEvent],
) -> tuple[int, int, int]:
    try:
        result = await client.send_events(token, batch)
    except PermanentDeliveryError as error:
        if error.status_code in {401, 403}:
            raise
        if len(batch) > 1:
            midpoint = len(batch) // 2
            left = await _deliver_batch(client, token, outbox, batch[:midpoint])
            right = await _deliver_batch(client, token, outbox, batch[midpoint:])
            return left[0] + right[0], left[1] + right[1], left[2] + right[2]
        outbox.quarantine([batch[0].id], reason=f"http_{error.status_code}")
        return 0, 0, 1
    if result.accepted + result.duplicates != len(batch):
        raise RuntimeError("backend did not account for the complete event batch")
    outbox.acknowledge([event.id for event in batch])
    return result.accepted, result.duplicates, 0


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
) -> RunResult:
    identity = load_or_create_identity(settings.state_directory / "identity.json")
    credentials_path = settings.state_directory / "credentials.json"
    credentials = load_credentials(credentials_path)
    outbox = Outbox(
        settings.state_directory / "outbox.sqlite3",
        max_events=settings.max_outbox_events,
    )
    owned_client = client is None
    resolved_client = client or AegisXClient(
        settings.api_url,
        timeout_seconds=settings.request_timeout_seconds,
    )
    try:
        resolved_collectors = collectors or [
            SystemCollector(),
            ProcessCollector(
                max_processes=settings.max_processes,
                state_path=settings.state_directory / "process-state.json",
            ),
            NetworkCollector(max_connections=settings.max_network_connections),
        ]
        events = [
            normalize_observation(observation)
            for collector in resolved_collectors
            for observation in _flatten(collector.collect())
        ]
        evicted = outbox.enqueue(events)
        accepted = 0
        duplicates = 0
        quarantined = 0
        try:
            if credentials is None:
                credentials = await resolved_client.register(_device_profile(identity.external_id))
                save_credentials(credentials_path, credentials)
            while batch := outbox.peek(settings.batch_size):
                delivered = await _deliver_batch(resolved_client, credentials.token, outbox, batch)
                accepted += delivered[0]
                duplicates += delivered[1]
                quarantined += delivered[2]
        except (httpx.TransportError, httpx.TimeoutException, TransientDeliveryError):
            return RunResult(
                accepted=accepted,
                duplicates=duplicates,
                queued=outbox.count(),
                evicted=evicted,
                quarantined=quarantined,
                delivery_status="deferred",
            )
        return RunResult(
            accepted=accepted,
            duplicates=duplicates,
            queued=outbox.count(),
            evicted=evicted,
            quarantined=quarantined,
            delivery_status="delivered",
        )
    finally:
        outbox.close()
        if owned_client and isinstance(resolved_client, AegisXClient):
            await resolved_client.close()
