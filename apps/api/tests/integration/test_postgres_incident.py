import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from aegisx_api.config import Settings
from aegisx_api.incident.policies import (
    IncidentDecision,
    IncidentPromotionPolicy,
    registry,
)
from aegisx_api.main import create_app
from aegisx_api.models.correlation import CorrelationCandidate
from aegisx_api.models.detection import Detection
from aegisx_api.models.device import Device
from aegisx_api.models.event import Event
from aegisx_api.models.incident import Incident


class EligiblePromotionPolicy(IncidentPromotionPolicy):
    def __init__(self, score_threshold: int = 30) -> None:
        self.policy_id = "TEST_POLICY_1"
        self.policy_version = 1
        self.supported_strategy_ids = ["TEST_STRATEGY"]
        self.name = "Test Policy"
        self.description = "Test policy for integration tests"
        self.score_threshold = score_threshold

    def evaluate(self, candidate: CorrelationCandidate) -> IncidentDecision | None:
        if candidate.aggregate_score >= self.score_threshold:
            return IncidentDecision(
                policy_id=self.policy_id,
                policy_version=self.policy_version,
                grouping_key=hashlib.sha256(str(candidate.device_id).encode("utf-8")).hexdigest(),
                title="Test Incident",
                summary="Test Summary",
                score_threshold=self.score_threshold,
                confidence_threshold="medium",
                trigger_candidate_id=candidate.id,
            )
        return None


@pytest.fixture(autouse=True)
def _setup_test_policy() -> None:
    registry.clear()
    registry.register(EligiblePromotionPolicy())
    yield
    registry.clear()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_incident_creation_and_attachment() -> None:
    database_url = os.getenv("AEGISX_TEST_POSTGRES_URL")
    if database_url is None:
        pytest.skip("AEGISX_TEST_POSTGRES_URL is not configured")
    assert database_url.startswith("postgresql+asyncpg://")

    app = create_app(Settings(_env_file=None, environment="test", database_url=database_url))
    async with app.router.lifespan_context(app):
        async with app.state.session_factory() as session:
            device = Device(
                external_id=f"test-device-{uuid4()}",
                name="Test Device",
                os="Linux",
                os_version="1.0",
                kernel="1.0",
                architecture="x86_64",
                token_digest=hashlib.sha256(b"token").hexdigest(),
            )
            session.add(device)
            await session.flush()
            device_id = device.id

            event1 = Event(
                id=uuid4(),
                device_id=device_id,
                schema_version=1,
                timestamp=datetime.now(UTC),
                event_type="test",
                source="test",
                severity_hint="low",
                data={},
                metadata_={},
            )
            session.add(event1)
            det1 = Detection(
                device_id=device_id,
                source_event=event1,
                rule_id="TEST_RULE",
                timestamp=event1.timestamp,
                severity="low",
                score_contribution=40,
                reason="test",
                evidence_event_ids=[str(event1.id)],
            )
            session.add(det1)
            await session.flush()

            # Create candidate 1
            candidate1 = CorrelationCandidate(
                correlation_key=hashlib.sha256(b"cand1").hexdigest(),
                device_id=device_id,
                strategy_id="TEST_STRATEGY",
                start_timestamp=event1.timestamp,
                end_timestamp=event1.timestamp,
                confidence="high",
                aggregate_score=40,
                reason="test",
                detections=[det1],
                events=[event1],
            )
            session.add(candidate1)
            await session.flush()

            # Process candidate 1
            async with session.begin_nested():
                await app.state.incident_service.process_candidate(session, candidate1)

            # Assert incident 1 created
            incident = await session.scalar(
                select(Incident)
                .where(Incident.device_id == device_id)
                .options(selectinload(Incident.candidates))
            )
            assert incident is not None
            assert incident.status == "OPEN"
            assert incident.disposition == "UNDETERMINED"
            assert incident.risk_score == 40
            assert len(incident.candidates) == 1
            assert incident.candidates[0].id == candidate1.id

            # Create candidate 2 (in window)
            event2 = Event(
                id=uuid4(),
                device_id=device_id,
                schema_version=1,
                timestamp=event1.timestamp + timedelta(seconds=10),
                event_type="test2",
                source="test",
                severity_hint="medium",
                data={},
                metadata_={},
            )
            session.add(event2)
            det2 = Detection(
                device_id=device_id,
                source_event=event2,
                rule_id="TEST_RULE_2",
                timestamp=event2.timestamp,
                severity="medium",
                score_contribution=30,
                reason="test2",
                evidence_event_ids=[str(event2.id)],
            )
            session.add(det2)
            await session.flush()

            candidate2 = CorrelationCandidate(
                correlation_key=hashlib.sha256(b"cand2").hexdigest(),
                device_id=device_id,
                strategy_id="TEST_STRATEGY",
                start_timestamp=event2.timestamp,
                end_timestamp=event2.timestamp,
                confidence="high",
                aggregate_score=30,
                reason="test",
                detections=[det2],
                events=[event2],
            )
            session.add(candidate2)
            await session.flush()

            # Process candidate 2
            async with session.begin_nested():
                await app.state.incident_service.process_candidate(session, candidate2)

            await session.refresh(incident, ["candidates", "detections", "events"])
            assert len(incident.candidates) == 2
            assert incident.risk_score == 70

            # Candidate 3 (outside window)
            event3 = Event(
                id=uuid4(),
                device_id=device_id,
                schema_version=1,
                timestamp=event1.timestamp + timedelta(hours=2),
                event_type="test3",
                source="test",
                severity_hint="low",
                data={},
                metadata_={},
            )
            session.add(event3)
            det3 = Detection(
                device_id=device_id,
                source_event=event3,
                rule_id="TEST_RULE_3",
                timestamp=event3.timestamp,
                severity="low",
                score_contribution=40,
                reason="test3",
                evidence_event_ids=[str(event3.id)],
            )
            session.add(det3)
            await session.flush()

            candidate3 = CorrelationCandidate(
                correlation_key=hashlib.sha256(b"cand3").hexdigest(),
                device_id=device_id,
                strategy_id="TEST_STRATEGY",
                start_timestamp=event3.timestamp,
                end_timestamp=event3.timestamp,
                confidence="high",
                aggregate_score=40,
                reason="test",
                detections=[det3],
                events=[event3],
            )
            session.add(candidate3)
            await session.flush()

            async with session.begin_nested():
                await app.state.incident_service.process_candidate(session, candidate3)

            incidents = list(
                (
                    await session.scalars(select(Incident).where(Incident.device_id == device_id))
                ).all()
            )
            assert len(incidents) == 2

            await session.delete(device)
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_incident_savepoint_failure_preserves_candidate() -> None:
    database_url = os.getenv("AEGISX_TEST_POSTGRES_URL")
    if database_url is None:
        pytest.skip("AEGISX_TEST_POSTGRES_URL is not configured")

    app = create_app(Settings(_env_file=None, environment="test", database_url=database_url))
    async with app.router.lifespan_context(app):
        async with app.state.session_factory() as session:
            device = Device(
                external_id=f"test-device-{uuid4()}",
                name="Test Device",
                os="Linux",
                os_version="1.0",
                kernel="1.0",
                architecture="x86_64",
                token_digest=hashlib.sha256(b"token2").hexdigest(),
            )
            session.add(device)
            await session.flush()

            event1 = Event(
                id=uuid4(),
                device_id=device.id,
                schema_version=1,
                timestamp=datetime.now(UTC),
                event_type="test",
                source="test",
                severity_hint="low",
                data={},
                metadata_={},
            )
            session.add(event1)
            det1 = Detection(
                device_id=device.id,
                source_event=event1,
                rule_id="TEST_RULE",
                timestamp=event1.timestamp,
                severity="low",
                score_contribution=40,
                reason="test",
                evidence_event_ids=[str(event1.id)],
            )
            session.add(det1)
            candidate1 = CorrelationCandidate(
                correlation_key=hashlib.sha256(b"fail_cand").hexdigest(),
                device_id=device.id,
                strategy_id="TEST_STRATEGY",
                start_timestamp=event1.timestamp,
                end_timestamp=event1.timestamp,
                confidence="high",
                aggregate_score=40,
                reason="test",
                detections=[det1],
                events=[event1],
            )
            session.add(candidate1)
            await session.flush()
            cand_id = candidate1.id

            # simulate savepoint failure
            try:
                async with session.begin_nested():
                    await app.state.incident_service.process_candidate(session, candidate1)
                    raise RuntimeError("Mock failure during incident promotion")
            except RuntimeError:
                pass

            await session.commit()

            # verify candidate exists but incident does not
        async with app.state.session_factory() as session:
            cand = await session.scalar(
                select(CorrelationCandidate).where(CorrelationCandidate.id == cand_id)
            )
            assert cand is not None

            inc = await session.scalar(
                select(func.count()).select_from(Incident).where(Incident.device_id == device.id)
            )
            assert inc == 0

            device = await session.scalar(select(Device).where(Device.id == cand.device_id))
            await session.delete(device)
            await session.commit()
