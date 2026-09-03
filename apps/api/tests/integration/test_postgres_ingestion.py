import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from aegisx_api.config import Settings
from aegisx_api.main import create_app
from aegisx_api.models.correlation import (
    CorrelationCandidate,
    correlation_candidate_detections,
    correlation_candidate_events,
)
from aegisx_api.models.detection import Detection
from aegisx_api.models.device import Device
from aegisx_api.models.event import Event


@pytest.mark.integration
@pytest.mark.asyncio
async def test_device_registration_and_event_ingestion_on_postgresql() -> None:
    database_url = os.getenv("AEGISX_TEST_POSTGRES_URL")
    if database_url is None:
        pytest.skip("AEGISX_TEST_POSTGRES_URL is not configured")
    assert database_url.startswith("postgresql+asyncpg://")

    external_id = f"postgres-integration-{uuid4()}"
    process_event_id = uuid4()
    listener_event_id = uuid4()
    repeated_listener_event_id = uuid4()
    process_timestamp = datetime.now(UTC).replace(microsecond=0)
    listener_timestamp = process_timestamp + timedelta(seconds=1)
    app = create_app(Settings(_env_file=None, environment="test", database_url=database_url))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            registration = await client.post(
                "/api/v1/devices/register",
                json={
                    "external_id": external_id,
                    "name": "PostgreSQL integration device",
                    "os": "Linux",
                    "os_version": "test",
                    "kernel": "test",
                    "architecture": "x86_64",
                },
            )
            assert registration.status_code == 201
            token = registration.json()["token"]

            process_ingestion = await client.post(
                "/api/v1/telemetry/events",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "events": [
                        {
                            "id": str(process_event_id),
                            "schema_version": 1,
                            "timestamp": process_timestamp.isoformat(),
                            "event_type": "process.started",
                            "source": "integration_test",
                            "severity_hint": "normal",
                            "data": {
                                "pid": 4242,
                                "ppid": 1,
                                "name": "python",
                                "executable": "/usr/bin/python3",
                                "user": "student",
                                "command_line": ["python3", "demo.py"],
                                "started_at": process_timestamp.isoformat(),
                            },
                            "metadata": {},
                        }
                    ]
                },
            )
            listener_ingestion = await client.post(
                "/api/v1/telemetry/events",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "events": [
                        {
                            "id": str(listener_event_id),
                            "schema_version": 1,
                            "timestamp": listener_timestamp.isoformat(),
                            "event_type": "network.listener_observed",
                            "source": "integration_test",
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
                    ]
                },
            )
            assert process_ingestion.status_code == 202
            assert process_ingestion.json() == {"accepted": 1, "duplicates": 0}
            assert listener_ingestion.status_code == 202
            assert listener_ingestion.json() == {"accepted": 1, "duplicates": 0}

        async with app.state.session_factory() as session:
            listener_event = await session.scalar(
                select(Event).where(Event.id == listener_event_id)
            )
            assert listener_event is not None
            assert listener_event.local_port == 8080
            assert listener_event.event_type == "network.listener_observed"

            detections = (
                await session.scalars(
                    select(Detection).where(
                        Detection.source_event_id.in_((process_event_id, listener_event_id))
                    )
                )
            ).all()
            assert {detection.rule_id for detection in detections} == {
                "PROCESS_STARTED",
                "LISTENER_OBSERVED",
            }
            listener_detection = next(
                detection for detection in detections if detection.rule_id == "LISTENER_OBSERVED"
            )
            assert listener_detection.severity == "low"
            assert listener_detection.score_contribution == 5
            assert listener_detection.evidence_event_ids == [str(listener_event_id)]

            device = await session.scalar(select(Device).where(Device.external_id == external_id))
            assert device is not None
            device_id = device.id
            candidate = await session.scalar(
                select(CorrelationCandidate)
                .where(CorrelationCandidate.device_id == device_id)
                .options(
                    selectinload(CorrelationCandidate.detections),
                    selectinload(CorrelationCandidate.events),
                )
            )
            assert candidate is not None
            assert candidate.device_id == device.id
            assert candidate.strategy_id == "PROCESS_LISTENER_ACTIVITY"
            assert candidate.start_timestamp == process_timestamp
            assert candidate.end_timestamp == listener_timestamp
            assert candidate.confidence == "low"
            assert candidate.aggregate_score == 5
            assert candidate.reason == (
                "A listener snapshot was associated with the recently started process identity."
            )
            assert len(candidate.correlation_key) == 64
            initial_candidate_id = candidate.id
            initial_detection_ids = {detection.id for detection in candidate.detections}
            initial_event_ids = {event.id for event in candidate.events}
            assert initial_detection_ids == {detection.id for detection in detections}
            assert initial_event_ids == {process_event_id, listener_event_id}
            assert (
                set(
                    (
                        await session.scalars(
                            select(correlation_candidate_detections.c.detection_id).where(
                                correlation_candidate_detections.c.candidate_id == candidate.id
                            )
                        )
                    ).all()
                )
                == initial_detection_ids
            )
            assert (
                set(
                    (
                        await session.scalars(
                            select(correlation_candidate_events.c.event_id).where(
                                correlation_candidate_events.c.candidate_id == candidate.id
                            )
                        )
                    ).all()
                )
                == initial_event_ids
            )

        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            repeated_ingestion = await client.post(
                "/api/v1/telemetry/events",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "events": [
                        {
                            "id": str(repeated_listener_event_id),
                            "schema_version": 1,
                            "timestamp": (listener_timestamp + timedelta(seconds=1)).isoformat(),
                            "event_type": "network.listener_observed",
                            "source": "integration_test",
                            "severity_hint": "normal",
                            "data": {
                                "pid": 4242,
                                "local_ip": "127.0.0.1",
                                "local_port": 8081,
                                "protocol": "tcp",
                                "state": "LISTEN",
                            },
                            "metadata": {},
                        }
                    ]
                },
            )
            assert repeated_ingestion.status_code == 202
            assert repeated_ingestion.json() == {"accepted": 1, "duplicates": 0}

        async with app.state.session_factory() as session:
            candidates = (
                await session.scalars(
                    select(CorrelationCandidate)
                    .where(CorrelationCandidate.device_id == device_id)
                    .options(
                        selectinload(CorrelationCandidate.detections),
                        selectinload(CorrelationCandidate.events),
                    )
                )
            ).all()
            assert len(candidates) == 1
            candidate = candidates[0]
            assert candidate.id == initial_candidate_id
            assert candidate.end_timestamp == listener_timestamp
            assert candidate.aggregate_score == 5
            assert {detection.id for detection in candidate.detections} == initial_detection_ids
            assert {event.id for event in candidate.events} == initial_event_ids

            device = await session.scalar(select(Device).where(Device.external_id == external_id))
            assert device is not None
            await session.delete(device)
            await session.commit()

            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(CorrelationCandidate)
                    .where(CorrelationCandidate.id == initial_candidate_id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(correlation_candidate_detections)
                    .where(correlation_candidate_detections.c.candidate_id == initial_candidate_id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(correlation_candidate_events)
                    .where(correlation_candidate_events.c.candidate_id == initial_candidate_id)
                )
                == 0
            )
