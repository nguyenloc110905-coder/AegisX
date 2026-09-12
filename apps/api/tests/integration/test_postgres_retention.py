import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from aegisx_api.config import Settings
from aegisx_api.main import create_app
from aegisx_api.maintenance.retention_service import RetentionService
from aegisx_api.models.correlation import CorrelationCandidate
from aegisx_api.models.detection import Detection
from aegisx_api.models.device import Device
from aegisx_api.models.event import Event
from aegisx_api.models.incident import Incident


def _event(device_id: object, event_type: str, ingested_at: datetime) -> Event:
    return Event(
        id=uuid4(),
        device_id=device_id,
        schema_version=1,
        timestamp=ingested_at,
        ingested_at=ingested_at,
        event_type=event_type,
        source="retention-test",
        severity_hint="informational",
        data={},
        metadata_={},
    )


def _detection(device_id: object, event: Event, rule_id: str) -> Detection:
    return Detection(
        device_id=device_id,
        source_event=event,
        rule_id=rule_id,
        timestamp=event.timestamp,
        severity="low",
        score_contribution=5,
        reason="retention test",
        evidence_event_ids=[str(event.id)],
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_and_dry_run_are_read_only_and_protect_higher_order_evidence() -> None:
    database_url = os.getenv("AEGISX_TEST_POSTGRES_URL")
    if database_url is None:
        pytest.skip("AEGISX_TEST_POSTGRES_URL is not configured")

    evaluation_time = datetime(2026, 9, 11, 12, tzinfo=UTC)
    old = evaluation_time - timedelta(days=31)
    exact_metric_cutoff = evaluation_time - timedelta(hours=24)
    recent_metric = exact_metric_cutoff + timedelta(microseconds=1)
    app = create_app(Settings(_env_file=None, environment="test", database_url=database_url))

    async with app.router.lifespan_context(app):
        async with app.state.session_factory() as session:
            device = Device(
                external_id=f"retention-{uuid4()}",
                name="Retention device",
                os="Linux",
                os_version="test",
                kernel="test",
                architecture="x86_64",
                token_digest=hashlib.sha256(str(uuid4()).encode()).hexdigest(),
            )
            session.add(device)
            await session.flush()

            deletable = _event(device.id, "process.resource_usage", exact_metric_cutoff)
            standalone_detection = _detection(device.id, deletable, "OLD_STANDALONE")
            recent = _event(device.id, "process.resource_usage", recent_metric)
            unknown = _event(device.id, "future.unknown", old)
            candidate_direct = _event(device.id, "process.started", old)
            candidate_indirect = _event(device.id, "process.started", old)
            candidate_detection = _detection(device.id, candidate_indirect, "CANDIDATE_LINKED")
            incident_direct = _event(device.id, "process.started", old)
            incident_indirect = _event(device.id, "process.started", old)
            incident_detection = _detection(device.id, incident_indirect, "INCIDENT_LINKED")
            session.add_all(
                [
                    deletable,
                    standalone_detection,
                    recent,
                    unknown,
                    candidate_direct,
                    candidate_indirect,
                    candidate_detection,
                    incident_direct,
                    incident_indirect,
                    incident_detection,
                ]
            )
            await session.flush()

            candidate = CorrelationCandidate(
                correlation_key=hashlib.sha256(str(uuid4()).encode()).hexdigest(),
                device_id=device.id,
                strategy_id="RETENTION_TEST",
                start_timestamp=old,
                end_timestamp=old,
                confidence="high",
                aggregate_score=10,
                reason="retention test",
                events=[candidate_direct],
                detections=[candidate_detection],
            )
            incident = Incident(
                incident_key=hashlib.sha256(str(uuid4()).encode()).hexdigest(),
                device_id=device.id,
                policy_id="RETENTION_TEST",
                policy_version=1,
                grouping_key=hashlib.sha256(str(uuid4()).encode()).hexdigest(),
                title="Retention test",
                summary="Retention test",
                status="OPEN",
                disposition="UNDETERMINED",
                severity="low",
                risk_score=10,
                confidence="high",
                promotion_score_threshold=10,
                promotion_confidence_threshold="high",
                evidence_window_seconds=3600,
                first_evidence_at=old,
                last_evidence_at=old,
                events=[incident_direct],
                detections=[incident_detection],
            )
            session.add_all([candidate, incident])
            await session.commit()
            before_events = int(await session.scalar(select(func.count()).select_from(Event)) or 0)

        service = RetentionService(app.state.session_factory)
        status = await service.data_status()
        report = await service.dry_run(evaluation_time)

        metric = next(rule for rule in report.rules if rule.event_type == "process.resource_usage")
        process = next(rule for rule in report.rules if rule.event_type == "process.started")
        assert metric.deletable_events == 1
        assert metric.deletable_detections == 1
        assert process.expired_events == 4
        assert process.protected_events == 4
        assert process.deletable_events == 0
        assert status.protected_event_count >= 4
        assert "future.unknown" in {row.event_type for row in status.event_types}

        async with app.state.session_factory() as session:
            assert (
                int(await session.scalar(select(func.count()).select_from(Event)) or 0)
                == before_events
            )
            await session.delete(await session.get(Device, device.id))
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_prune_deletes_only_expired_unprotected_evidence_and_is_idempotent() -> None:
    database_url = os.getenv("AEGISX_TEST_POSTGRES_URL")
    if database_url is None:
        pytest.skip("AEGISX_TEST_POSTGRES_URL is not configured")

    evaluation_time = datetime(2026, 9, 11, 12, tzinfo=UTC)
    old = evaluation_time - timedelta(days=31)
    recent_time = evaluation_time - timedelta(hours=1)
    app = create_app(Settings(_env_file=None, environment="test", database_url=database_url))

    async with app.router.lifespan_context(app):
        async with app.state.session_factory() as session:
            device = Device(
                external_id=f"retention-apply-{uuid4()}",
                name="Retention apply device",
                os="Linux",
                os_version="test",
                kernel="test",
                architecture="x86_64",
                token_digest=hashlib.sha256(str(uuid4()).encode()).hexdigest(),
            )
            session.add(device)
            await session.flush()

            expired = _event(device.id, "process.started", old)
            expired_detection = _detection(device.id, expired, "EXPIRED_STANDALONE")
            recent = _event(device.id, "process.started", recent_time)
            unknown = _event(device.id, "future.unknown", old)
            protected = _event(device.id, "process.started", old)
            protected_detection = _detection(device.id, protected, "PROTECTED")
            candidate = CorrelationCandidate(
                correlation_key=hashlib.sha256(str(uuid4()).encode()).hexdigest(),
                device_id=device.id,
                strategy_id="RETENTION_APPLY_TEST",
                start_timestamp=old,
                end_timestamp=old,
                confidence="high",
                aggregate_score=10,
                reason="retention apply test",
                detections=[protected_detection],
            )
            session.add_all(
                [
                    expired,
                    expired_detection,
                    recent,
                    unknown,
                    protected,
                    protected_detection,
                    candidate,
                ]
            )
            await session.commit()
            device_id = device.id
            candidate_id = candidate.id

        service = RetentionService(app.state.session_factory)
        result = await service.prune(evaluation_time, batch_size=1)
        repeated = await service.prune(evaluation_time, batch_size=1)

        assert result.deleted_events == 1
        assert result.deleted_detections == 1
        assert result.completed is True
        assert repeated.deleted_events == 0
        assert repeated.deleted_detections == 0

        async with app.state.session_factory() as session:
            assert await session.get(Event, expired.id) is None
            assert await session.get(Detection, expired_detection.id) is None
            assert await session.get(Event, recent.id) is not None
            assert await session.get(Event, unknown.id) is not None
            assert await session.get(Event, protected.id) is not None
            assert await session.get(Detection, protected_detection.id) is not None
            assert await session.get(CorrelationCandidate, candidate_id) is not None
            await session.delete(await session.get(Device, device_id))
            await session.commit()
