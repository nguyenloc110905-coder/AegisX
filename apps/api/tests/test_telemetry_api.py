from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from aegisx_api.config import Settings
from aegisx_api.db.base import Base
from aegisx_api.main import create_app
from aegisx_api.models.correlation import CorrelationCandidate
from aegisx_api.models.detection import Detection
from aegisx_api.models.event import Event
from aegisx_api.services.telemetry_ingestion import TelemetryIngestionService


@pytest.fixture
async def app_and_client(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'telemetry.db'}",
    )
    app = create_app(settings)
    async with app.state.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield app, client
    await app.state.engine.dispose()


async def register(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/api/v1/devices/register",
        json={
            "external_id": "telemetry-device-01",
            "name": "Telemetry Device",
            "os": "Linux",
            "os_version": "Fedora 42",
            "kernel": "6.15.9",
            "architecture": "x86_64",
        },
    )
    return response.json()["token"]


def process_started_event(
    event_id: str,
    *,
    timestamp: datetime | None = None,
    started_at: datetime | None = None,
) -> dict:
    observed_at = timestamp or datetime.now(UTC)
    return {
        "id": event_id,
        "schema_version": 1,
        "timestamp": observed_at.isoformat(),
        "event_type": "process.started",
        "source": "process_collector",
        "severity_hint": "normal",
        "data": {
            "pid": 4242,
            "ppid": 1,
            "name": "python",
            "executable": "/usr/bin/python3",
            "user": "student",
            "command_line": ["python3", "demo.py"],
            "started_at": (started_at or observed_at).isoformat(),
        },
        "metadata": {},
    }


def listener_observed_event(event_id: str, *, timestamp: datetime) -> dict:
    return {
        "id": event_id,
        "schema_version": 1,
        "timestamp": timestamp.isoformat(),
        "event_type": "network.listener_observed",
        "source": "network_collector",
        "severity_hint": "normal",
        "data": {
            "pid": 4242,
            "local_ip": "127.0.0.1",
            "local_port": 8080,
            "protocol": "tcp",
            "state": "LISTEN",
        },
        "metadata": {},
    }


class RaisingCorrelationService:
    async def correlate(
        self,
        session: AsyncSession,
        device_id: UUID,
        new_detections: Sequence[Detection],
        window: timedelta,
    ) -> int:
        session.add(
            CorrelationCandidate(
                correlation_key="f" * 64,
                device_id=device_id,
                strategy_id="TEST_PARTIAL_FAILURE",
                start_timestamp=new_detections[0].timestamp,
                end_timestamp=new_detections[-1].timestamp,
                confidence="low",
                aggregate_score=5,
                reason="Temporary candidate created before a forced test failure.",
                detections=list(new_detections),
                events=[detection.source_event for detection in new_detections],
            )
        )
        await session.flush()
        raise RuntimeError("forced correlation failure")


@pytest.mark.asyncio
async def test_ingestion_requires_valid_device_token(app_and_client) -> None:
    _, client = app_and_client
    response = await client.post(
        "/api/v1/telemetry/events",
        headers={"Authorization": "Bearer invalid-token"},
        json={"events": [process_started_event(str(uuid4()))]},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_device_token"


@pytest.mark.asyncio
async def test_ingestion_is_typed_and_idempotent(app_and_client) -> None:
    app, client = app_and_client
    token = await register(client)
    event_id = str(uuid4())
    request = {"events": [process_started_event(event_id)]}
    headers = {"Authorization": f"Bearer {token}"}

    first = await client.post("/api/v1/telemetry/events", headers=headers, json=request)
    second = await client.post("/api/v1/telemetry/events", headers=headers, json=request)

    assert first.status_code == 202
    assert first.json() == {"accepted": 1, "duplicates": 0}
    assert second.status_code == 202
    assert second.json() == {"accepted": 0, "duplicates": 1}
    async with app.state.session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(Event))
        detection_count = await session.scalar(select(func.count()).select_from(Detection))
    assert count == 1
    assert detection_count == 1


@pytest.mark.asyncio
async def test_irrelevant_event_persists_without_detection(app_and_client) -> None:
    app, client = app_and_client
    token = await register(client)
    response = await client.post(
        "/api/v1/telemetry/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "id": str(uuid4()),
                    "schema_version": 1,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "event_type": "system.status",
                    "source": "system_collector",
                    "severity_hint": "normal",
                    "data": {
                        "hostname": "test",
                        "os": "Linux",
                        "kernel": "test",
                        "uptime_seconds": 1,
                        "cpu_count": 1,
                        "memory_total_bytes": 1024,
                    },
                    "metadata": {},
                }
            ]
        },
    )

    assert response.status_code == 202
    async with app.state.session_factory() as session:
        detection_count = await session.scalar(select(func.count()).select_from(Detection))
    assert detection_count == 0


@pytest.mark.asyncio
async def test_ingestion_rejects_payload_for_wrong_event_type(app_and_client) -> None:
    _, client = app_and_client
    token = await register(client)
    event = process_started_event(str(uuid4()))
    event["event_type"] = "system.status"

    response = await client.post(
        "/api/v1/telemetry/events",
        headers={"Authorization": f"Bearer {token}"},
        json={"events": [event]},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingestion_accepts_typed_network_listener(app_and_client) -> None:
    app, client = app_and_client
    token = await register(client)
    event_id = str(uuid4())
    event = {
        "id": event_id,
        "schema_version": 1,
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": "network.listener_observed",
        "source": "network_collector",
        "severity_hint": "normal",
        "data": {
            "pid": 4242,
            "local_ip": "127.0.0.1",
            "local_port": 8080,
            "protocol": "tcp",
            "state": "LISTEN",
        },
        "metadata": {},
    }

    response = await client.post(
        "/api/v1/telemetry/events",
        headers={"Authorization": f"Bearer {token}"},
        json={"events": [event]},
    )

    assert response.status_code == 202
    async with app.state.session_factory() as session:
        stored = await session.scalar(select(Event).where(Event.id == UUID(event_id)))
    assert stored is not None
    assert stored.local_port == 8080


@pytest.mark.asyncio
async def test_ingestion_accepts_typed_process_exit_without_detection(app_and_client) -> None:
    app, client = app_and_client
    token = await register(client)
    event_id = uuid4()
    response = await client.post(
        "/api/v1/telemetry/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "id": str(event_id),
                    "schema_version": 1,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "event_type": "process.exited",
                    "source": "process_collector",
                    "severity_hint": "normal",
                    "data": {
                        "pid": 4242,
                        "started_at": "2026-09-03T01:00:00+00:00",
                    },
                    "metadata": {},
                }
            ]
        },
    )

    assert response.status_code == 202
    async with app.state.session_factory() as session:
        stored = await session.get(Event, event_id)
        detection_count = await session.scalar(select(func.count()).select_from(Detection))
    assert stored is not None
    assert stored.event_type == "process.exited"
    assert stored.process_id == 4242
    assert detection_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "data"),
    [
        (
            "network.listener_opened",
            {
                "pid": 4242,
                "local_ip": "127.0.0.1",
                "local_port": 8080,
                "protocol": "tcp",
                "state": "LISTEN",
            },
        ),
        (
            "network.listener_closed",
            {
                "pid": None,
                "local_ip": "::",
                "local_port": 5353,
                "protocol": "udp",
                "state": "NONE",
            },
        ),
        (
            "network.connection_opened",
            {
                "pid": 4242,
                "local_ip": "192.0.2.10",
                "local_port": 50000,
                "remote_ip": "198.51.100.20",
                "remote_port": 443,
                "protocol": "tcp",
                "state": "ESTABLISHED",
            },
        ),
        (
            "network.connection_closed",
            {
                "pid": None,
                "local_ip": "192.0.2.10",
                "local_port": 50000,
                "remote_ip": "198.51.100.20",
                "remote_port": 443,
                "protocol": "tcp",
                "state": "ESTABLISHED",
            },
        ),
    ],
)
async def test_ingestion_accepts_typed_network_transition(
    app_and_client,
    event_type: str,
    data: dict,
) -> None:
    app, client = app_and_client
    token = await register(client)
    event_id = uuid4()

    response = await client.post(
        "/api/v1/telemetry/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                {
                    "id": str(event_id),
                    "schema_version": 1,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "event_type": event_type,
                    "source": "network_collector",
                    "severity_hint": "normal",
                    "data": data,
                    "metadata": {},
                }
            ]
        },
    )

    assert response.status_code == 202
    async with app.state.session_factory() as session:
        stored = await session.get(Event, event_id)
        detection_count = await session.scalar(select(func.count()).select_from(Detection))
    assert stored is not None
    assert stored.event_type == event_type
    assert detection_count == 0


@pytest.mark.asyncio
async def test_ingestion_persists_one_immutable_candidate_for_repeated_evidence(
    app_and_client,
) -> None:
    app, client = app_and_client
    token = await register(client)
    headers = {"Authorization": f"Bearer {token}"}
    process_timestamp = datetime(2026, 9, 3, 1, 0, tzinfo=UTC)
    listener_timestamp = process_timestamp + timedelta(minutes=1)
    process_event_id = uuid4()
    listener_event_id = uuid4()
    repeated_listener_event_id = uuid4()
    process_request = {
        "events": [
            process_started_event(
                str(process_event_id),
                timestamp=process_timestamp,
                started_at=process_timestamp,
            )
        ]
    }
    listener_request = {
        "events": [listener_observed_event(str(listener_event_id), timestamp=listener_timestamp)]
    }

    process_response = await client.post(
        "/api/v1/telemetry/events", headers=headers, json=process_request
    )
    listener_response = await client.post(
        "/api/v1/telemetry/events", headers=headers, json=listener_request
    )

    assert process_response.status_code == 202
    assert listener_response.status_code == 202
    async with app.state.session_factory() as session:
        candidate = await session.scalar(
            select(CorrelationCandidate).options(
                selectinload(CorrelationCandidate.detections),
                selectinload(CorrelationCandidate.events),
            )
        )
        assert candidate is not None
        original = {
            "id": candidate.id,
            "correlation_key": candidate.correlation_key,
            "end_timestamp": candidate.end_timestamp,
            "aggregate_score": candidate.aggregate_score,
            "detection_ids": {detection.id for detection in candidate.detections},
            "event_ids": {event.id for event in candidate.events},
        }
        assert candidate.strategy_id == "PROCESS_LISTENER_ACTIVITY"
        assert candidate.confidence == "low"
        assert candidate.aggregate_score == 5
        assert candidate.reason == (
            "A listener snapshot was associated with the recently started process identity."
        )
        assert candidate.start_timestamp == process_timestamp.replace(tzinfo=None)
        assert candidate.end_timestamp == listener_timestamp.replace(tzinfo=None)
        assert len(candidate.detections) == 2
        assert {event.id for event in candidate.events} == {
            process_event_id,
            listener_event_id,
        }

    repeated_response = await client.post(
        "/api/v1/telemetry/events",
        headers=headers,
        json={
            "events": [
                listener_observed_event(
                    str(repeated_listener_event_id),
                    timestamp=listener_timestamp + timedelta(minutes=1),
                )
            ]
        },
    )
    duplicate_response = await client.post(
        "/api/v1/telemetry/events", headers=headers, json=listener_request
    )

    assert repeated_response.status_code == 202
    assert repeated_response.json() == {"accepted": 1, "duplicates": 0}
    assert duplicate_response.status_code == 202
    assert duplicate_response.json() == {"accepted": 0, "duplicates": 1}
    async with app.state.session_factory() as session:
        candidates = (
            await session.scalars(
                select(CorrelationCandidate).options(
                    selectinload(CorrelationCandidate.detections),
                    selectinload(CorrelationCandidate.events),
                )
            )
        ).all()
        assert len(candidates) == 1
        persisted = candidates[0]
        assert {
            "id": persisted.id,
            "correlation_key": persisted.correlation_key,
            "end_timestamp": persisted.end_timestamp,
            "aggregate_score": persisted.aggregate_score,
            "detection_ids": {detection.id for detection in persisted.detections},
            "event_ids": {event.id for event in persisted.events},
        } == original


@pytest.mark.asyncio
async def test_new_detection_cannot_persist_a_historical_only_correlation(
    app_and_client,
) -> None:
    app, client = app_and_client
    token = await register(client)
    headers = {"Authorization": f"Bearer {token}"}
    process_a_timestamp = datetime(2026, 9, 3, 0, 0, tzinfo=UTC)
    process_b_timestamp = process_a_timestamp + timedelta(minutes=4)
    listener_one_timestamp = process_a_timestamp + timedelta(minutes=5)
    listener_two_timestamp = process_a_timestamp + timedelta(minutes=6)
    process_a_event_id = uuid4()
    process_b_event_id = uuid4()
    listener_one_event_id = uuid4()
    listener_two_event_id = uuid4()
    events = (
        process_started_event(
            str(process_a_event_id),
            timestamp=process_a_timestamp,
            started_at=process_a_timestamp,
        ),
        process_started_event(
            str(process_b_event_id),
            timestamp=process_b_timestamp,
            started_at=process_b_timestamp,
        ),
        listener_observed_event(str(listener_one_event_id), timestamp=listener_one_timestamp),
        listener_observed_event(str(listener_two_event_id), timestamp=listener_two_timestamp),
    )

    for index, event in enumerate(events):
        response = await client.post(
            "/api/v1/telemetry/events",
            headers=headers,
            json={"events": [event]},
        )
        assert response.status_code == 202
        assert response.json() == {"accepted": 1, "duplicates": 0}
        if index == 2:
            async with app.state.session_factory() as session:
                candidate_count = await session.scalar(
                    select(func.count()).select_from(CorrelationCandidate)
                )
            assert candidate_count == 0

    async with app.state.session_factory() as session:
        event_count = await session.scalar(select(func.count()).select_from(Event))
        detection_count = await session.scalar(select(func.count()).select_from(Detection))
        candidate = await session.scalar(
            select(CorrelationCandidate).options(selectinload(CorrelationCandidate.events))
        )
    assert event_count == 4
    assert detection_count == 4
    assert candidate is not None
    assert candidate.start_timestamp == process_b_timestamp.replace(tzinfo=None)
    assert candidate.end_timestamp == listener_two_timestamp.replace(tzinfo=None)
    assert {event.id for event in candidate.events} == {
        process_b_event_id,
        listener_two_event_id,
    }


@pytest.mark.asyncio
async def test_correlation_failure_preserves_authoritative_event_and_detection_rows(
    app_and_client,
) -> None:
    app, client = app_and_client
    app.state.telemetry_ingestion_service = TelemetryIngestionService(
        app.state.detection_engine,
        RaisingCorrelationService(),
        timedelta(seconds=app.state.settings.correlation_window_seconds),
    )
    token = await register(client)
    timestamp = datetime(2026, 9, 3, 2, 0, tzinfo=UTC)
    response = await client.post(
        "/api/v1/telemetry/events",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "events": [
                process_started_event(str(uuid4()), timestamp=timestamp, started_at=timestamp),
                listener_observed_event(str(uuid4()), timestamp=timestamp + timedelta(minutes=1)),
            ]
        },
    )

    assert response.status_code == 202
    assert response.json() == {"accepted": 2, "duplicates": 0}
    async with app.state.session_factory() as session:
        event_count = await session.scalar(select(func.count()).select_from(Event))
        detection_count = await session.scalar(select(func.count()).select_from(Detection))
        candidate_count = await session.scalar(
            select(func.count()).select_from(CorrelationCandidate)
        )
    assert event_count == 2
    assert detection_count == 2
    assert candidate_count == 0


@pytest.mark.asyncio
async def test_ingestion_enforces_configured_batch_limit(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'batch-limit.db'}",
        telemetry_batch_limit=1,
    )
    app = create_app(settings)
    async with app.state.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await register(client)
        response = await client.post(
            "/api/v1/telemetry/events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "events": [
                    process_started_event(str(uuid4())),
                    process_started_event(str(uuid4())),
                ]
            },
        )
    await app.state.engine.dispose()

    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "telemetry_batch_too_large", "limit": 1}
