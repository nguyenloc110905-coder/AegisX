from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from aegisx_api.console.repository import ConsoleRepository
from aegisx_api.db.base import Base
from aegisx_api.models.correlation import CorrelationCandidate
from aegisx_api.models.detection import Detection
from aegisx_api.models.device import Device
from aegisx_api.models.event import Event
from aegisx_api.models.incident import Incident


@pytest.mark.asyncio
async def test_repository_loads_bounded_display_records_without_device_secret() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    device_id = uuid4()
    event_id = uuid4()
    detection_id = uuid4()
    async with session_factory() as session:
        session.add(
            Device(
                id=device_id,
                external_id="console-device",
                name="workstation",
                os="Linux",
                os_version="Test Linux",
                kernel="6.12",
                architecture="x86_64",
                token_digest="secret-digest-must-not-leak",  # noqa: S106
                is_active=True,
                last_seen_at=now,
            )
        )
        session.add(
            Event(
                id=event_id,
                device_id=device_id,
                schema_version=1,
                timestamp=now,
                event_type="process.started",
                source="test",
                severity_hint="normal",
                data={"pid": 42},
                metadata_={},
                process_id=42,
                parent_process_id=1,
                executable="/usr/bin/python",
            )
        )
        session.add(
            Detection(
                id=detection_id,
                device_id=device_id,
                source_event_id=event_id,
                rule_id="PROCESS_STARTED",
                timestamp=now,
                severity="informational",
                score_contribution=0,
                reason="Verified process start transition.",
                evidence_event_ids=[str(event_id)],
            )
        )
        session.add(
            CorrelationCandidate(
                device_id=device_id,
                correlation_key="a" * 64,
                strategy_id="PROCESS_LISTENER_ACTIVITY",
                start_timestamp=now,
                end_timestamp=now,
                confidence="low",
                aggregate_score=5,
                reason="Observed activity.",
            )
        )
        session.add(
            Incident(
                device_id=device_id,
                incident_key="b" * 64,
                policy_id="TEST_POLICY",
                policy_version=1,
                grouping_key="c" * 64,
                title="Test incident",
                summary="Test evidence summary.",
                status="OPEN",
                disposition="UNDETERMINED",
                severity="medium",
                risk_score=40,
                confidence="medium",
                promotion_score_threshold=30,
                promotion_confidence_threshold="medium",
                evidence_window_seconds=3600,
                first_evidence_at=now,
                last_evidence_at=now,
            )
        )
        await session.commit()

    repository = ConsoleRepository(session_factory, engine=engine)
    snapshot = await repository.load(limit=1)

    assert snapshot.counts.devices == 1
    assert snapshot.counts.events == 1
    assert snapshot.counts.detections == 1
    assert snapshot.counts.candidates == 1
    assert snapshot.counts.open_incidents == 1
    assert snapshot.devices[0].name == "workstation"
    assert not hasattr(snapshot.devices[0], "token_digest")
    assert snapshot.events[0].event_type == "process.started"
    assert snapshot.detections[0].rule_id == "PROCESS_STARTED"
    assert snapshot.candidates[0].strategy_id == "PROCESS_LISTENER_ACTIVITY"
    assert snapshot.incidents[0].title == "Test incident"

    await repository.close()
