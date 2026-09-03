from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from aegisx_api.db.base import Base
from aegisx_api.models.correlation import CorrelationCandidate
from aegisx_api.models.detection import Detection
from aegisx_api.models.device import Device
from aegisx_api.models.event import Event


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as database_session:
        yield database_session
    await engine.dispose()


@pytest.mark.asyncio
async def test_device_and_event_are_persisted_with_relationship(session) -> None:
    device = Device(
        external_id="fedora-laptop-01",
        name="Fedora Laptop",
        os="Linux",
        os_version="Fedora 42",
        kernel="6.15.9",
        architecture="x86_64",
        token_digest="a" * 64,
    )
    event = Event(
        id=uuid4(),
        device=device,
        schema_version=1,
        timestamp=datetime.now(UTC),
        event_type="system.status",
        source="system_collector",
        severity_hint="normal",
        data={"hostname": "fedora-laptop"},
        metadata_={},
    )
    session.add(event)
    await session.commit()

    persisted = await session.scalar(select(Event).where(Event.id == event.id))

    assert persisted is not None
    assert persisted.device_id == device.id
    assert persisted.event_type == "system.status"


@pytest.mark.asyncio
async def test_device_external_id_is_unique(session) -> None:
    common = {
        "external_id": "same-device",
        "name": "Laptop",
        "os": "Linux",
        "os_version": "Fedora 42",
        "kernel": "6.15.9",
        "architecture": "x86_64",
    }
    session.add(Device(**common, token_digest="a" * 64))
    await session.commit()
    session.add(Device(**common, token_digest="b" * 64))

    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_detection_persists_traceable_evidence_and_relationships(session) -> None:
    device = Device(
        external_id="detection-device",
        name="Detection Device",
        os="Linux",
        os_version="test",
        kernel="test",
        architecture="x86_64",
        token_digest="c" * 64,
    )
    event = Event(
        id=uuid4(),
        device=device,
        schema_version=1,
        timestamp=datetime.now(UTC),
        event_type="process.started",
        source="test",
        severity_hint="normal",
        data={"pid": 42, "name": "python"},
        metadata_={},
    )
    detection = Detection(
        device=device,
        source_event=event,
        rule_id="PROCESS_STARTED",
        timestamp=event.timestamp,
        severity="informational",
        score_contribution=0,
        reason="Process python (PID 42) was newly observed after the process baseline.",
        evidence_event_ids=[str(event.id)],
    )
    session.add(detection)
    await session.commit()

    persisted = await session.scalar(select(Detection).where(Detection.id == detection.id))

    assert persisted is not None
    assert persisted.device_id == device.id
    assert persisted.source_event_id == event.id
    assert persisted.evidence_event_ids == [str(event.id)]
    assert persisted.source_event.id == event.id

    await session.delete(event)
    await session.commit()
    count = await session.scalar(select(func.count()).select_from(Detection))
    assert count == 0


@pytest.mark.asyncio
async def test_detection_rejects_score_above_100(session) -> None:
    device = Device(
        external_id="invalid-score-device",
        name="Invalid Score Device",
        os="Linux",
        os_version="test",
        kernel="test",
        architecture="x86_64",
        token_digest="d" * 64,
    )
    event = Event(
        id=uuid4(),
        device=device,
        schema_version=1,
        timestamp=datetime.now(UTC),
        event_type="system.status",
        source="test",
        severity_hint="normal",
        data={},
        metadata_={},
    )
    session.add(
        Detection(
            device=device,
            source_event=event,
            rule_id="INVALID",
            timestamp=event.timestamp,
            severity="low",
            score_contribution=101,
            reason="invalid score",
            evidence_event_ids=[str(event.id)],
        )
    )

    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_correlation_candidate_persists_relational_evidence_and_reverse_relationships(
    session,
) -> None:
    device = Device(
        external_id="correlation-device",
        name="Correlation Device",
        os="Linux",
        os_version="test",
        kernel="test",
        architecture="x86_64",
        token_digest="e" * 64,
    )
    process_event = Event(
        id=uuid4(),
        device=device,
        schema_version=1,
        timestamp=datetime.now(UTC),
        event_type="process.started",
        source="test",
        severity_hint="normal",
        data={"pid": 42, "started_at": "2026-09-03T00:00:00+00:00"},
        metadata_={},
    )
    listener_event = Event(
        id=uuid4(),
        device=device,
        schema_version=1,
        timestamp=datetime.now(UTC),
        event_type="network.listener_observed",
        source="test",
        severity_hint="normal",
        data={"pid": 42},
        metadata_={},
    )
    process_detection = Detection(
        device=device,
        source_event=process_event,
        rule_id="PROCESS_STARTED",
        timestamp=process_event.timestamp,
        severity="informational",
        score_contribution=0,
        reason="Process was newly observed after the process baseline.",
        evidence_event_ids=[str(process_event.id)],
    )
    listener_detection = Detection(
        device=device,
        source_event=listener_event,
        rule_id="LISTENER_OBSERVED",
        timestamp=listener_event.timestamp,
        severity="low",
        score_contribution=5,
        reason="A listening socket was observed for the process.",
        evidence_event_ids=[str(listener_event.id)],
    )
    candidate = CorrelationCandidate(
        device=device,
        correlation_key="a" * 64,
        strategy_id="PROCESS_LISTENER_ACTIVITY",
        start_timestamp=process_event.timestamp,
        end_timestamp=listener_event.timestamp,
        confidence="low",
        aggregate_score=5,
        reason="A listener snapshot was associated with the recently started process identity.",
        detections=[process_detection, listener_detection],
        events=[process_event, listener_event],
    )
    session.add(candidate)
    await session.commit()

    persisted = await session.scalar(
        select(CorrelationCandidate).where(CorrelationCandidate.id == candidate.id)
    )

    assert persisted is not None
    assert persisted.device_id == device.id
    assert {detection.id for detection in persisted.detections} == {
        process_detection.id,
        listener_detection.id,
    }
    assert {event.id for event in persisted.events} == {process_event.id, listener_event.id}
    assert persisted in process_detection.correlation_candidates
    assert persisted in listener_event.correlation_candidates


@pytest.mark.asyncio
async def test_correlation_candidate_rejects_duplicate_key(session) -> None:
    device = Device(
        external_id="duplicate-correlation-device",
        name="Duplicate Correlation Device",
        os="Linux",
        os_version="test",
        kernel="test",
        architecture="x86_64",
        token_digest="f" * 64,
    )
    candidate_fields = {
        "device": device,
        "correlation_key": "b" * 64,
        "strategy_id": "PROCESS_LISTENER_ACTIVITY",
        "start_timestamp": datetime.now(UTC),
        "end_timestamp": datetime.now(UTC),
        "confidence": "low",
        "aggregate_score": 5,
        "reason": "A neutral candidate reason.",
    }
    session.add(CorrelationCandidate(**candidate_fields))
    await session.commit()
    session.add(CorrelationCandidate(**candidate_fields))

    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_correlation_candidate_rejects_score_above_100(session) -> None:
    device = Device(
        external_id="invalid-correlation-score-device",
        name="Invalid Correlation Score Device",
        os="Linux",
        os_version="test",
        kernel="test",
        architecture="x86_64",
        token_digest="0" * 64,
    )
    session.add(
        CorrelationCandidate(
            device=device,
            correlation_key="c" * 64,
            strategy_id="PROCESS_LISTENER_ACTIVITY",
            start_timestamp=datetime.now(UTC),
            end_timestamp=datetime.now(UTC),
            confidence="low",
            aggregate_score=101,
            reason="A neutral candidate reason.",
        )
    )

    with pytest.raises(IntegrityError):
        await session.commit()
