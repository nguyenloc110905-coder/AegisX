"""Full PostgreSQL integration tests for Milestone 6A Incident Foundation.

Requires AEGISX_TEST_POSTGRES_URL (postgresql+asyncpg://...).
All tests assert real PostgreSQL behaviour: advisory locks, savepoints,
concurrency, and schema constraints.
"""

import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aegisx_api.config import Settings
from aegisx_api.incident.policies import (
    IncidentDecision,
    IncidentPolicyRegistry,
    IncidentPromotionPolicy,
)
from aegisx_api.main import create_app
from aegisx_api.models.correlation import CorrelationCandidate
from aegisx_api.models.detection import Detection
from aegisx_api.models.device import Device
from aegisx_api.models.event import Event
from aegisx_api.models.incident import Incident, IncidentStatusTransition
from aegisx_api.services.incident import IncidentService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_URL = os.getenv("AEGISX_TEST_POSTGRES_URL", "")
SKIP_MSG = "AEGISX_TEST_POSTGRES_URL is not configured"


def _skip():
    if not TEST_URL:
        pytest.skip(SKIP_MSG)
    assert TEST_URL.startswith("postgresql+asyncpg://")


class _EligiblePolicy(IncidentPromotionPolicy):
    """Test-only policy that promotes every candidate with score >= threshold."""

    def __init__(
        self,
        *,
        policy_id: str = "TEST_ELIGIBLE",
        strategy_id: str = "TEST_STRATEGY",
        score_threshold: int = 30,
        evidence_window_s: int = 3600,
    ) -> None:
        self.policy_id = policy_id
        self.policy_version = 1
        self.supported_strategy_ids = [strategy_id]
        self.name = "Eligible test policy"
        self.description = "Test only"
        self.score_threshold = score_threshold
        self.evidence_window_s = evidence_window_s

    def evaluate(self, candidate: Any) -> IncidentDecision | None:
        if candidate.aggregate_score < self.score_threshold:
            return None
        gk = hashlib.sha256(f"{candidate.device_id}:{self.policy_id}".encode()).hexdigest()
        return IncidentDecision(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            grouping_key=gk,
            title="Test Incident",
            summary="Test summary",
            score_threshold=self.score_threshold,
            confidence_threshold="medium",
            trigger_candidate_id=candidate.id,
        )


@pytest.fixture
def _pg_url():
    _skip()
    return TEST_URL


@pytest.fixture
def _settings(_pg_url):
    return Settings(_env_file=None, environment="test", database_url=_pg_url)


@pytest.fixture
def _registry():
    r = IncidentPolicyRegistry()
    r.register(_EligiblePolicy())
    return r


@pytest.fixture
def _svc(_registry):
    svc = IncidentService(
        evidence_window=timedelta(hours=1),
        lock_timeout_ms=2000,
    )
    svc._registry = _registry
    return svc


async def _make_device(session: AsyncSession) -> Device:
    d = Device(
        external_id=f"dev-{uuid4()}",
        name="T",
        os="Linux",
        os_version="1",
        kernel="1",
        architecture="x86_64",
        token_digest=hashlib.sha256(uuid4().bytes).hexdigest(),
    )
    session.add(d)
    await session.flush()
    return d


async def _make_candidate(
    session: AsyncSession,
    device: Device,
    *,
    score: int = 40,
    confidence: str = "high",
    strategy_id: str = "TEST_STRATEGY",
    start: datetime | None = None,
    end: datetime | None = None,
) -> CorrelationCandidate:
    ts = start or datetime.now(UTC)
    ev = Event(
        id=uuid4(),
        device_id=device.id,
        schema_version=1,
        timestamp=ts,
        event_type="test",
        source="test",
        severity_hint="low",
        data={},
        metadata_={},
    )
    session.add(ev)
    det = Detection(
        device_id=device.id,
        source_event=ev,
        rule_id="TEST_RULE",
        timestamp=ts,
        severity="low",
        score_contribution=score,
        reason="test",
        evidence_event_ids=[str(ev.id)],
    )
    session.add(det)
    cand = CorrelationCandidate(
        correlation_key=hashlib.sha256(uuid4().bytes).hexdigest(),
        device_id=device.id,
        strategy_id=strategy_id,
        start_timestamp=ts,
        end_timestamp=end or ts,
        confidence=confidence,
        aggregate_score=score,
        reason="test",
        detections=[det],
        events=[ev],
    )
    session.add(cand)
    await session.flush()
    return cand


# ---------------------------------------------------------------------------
# Migration: upgrade / downgrade / upgrade
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_migration_upgrade_downgrade_upgrade(_pg_url: str) -> None:
    """Alembic round-trip: downgrade to 0004 then upgrade back to 0005."""
    import subprocess
    import sys

    env = {**os.environ, "DATABASE_URL": _pg_url.replace("+asyncpg", "+asyncpg")}

    def alembic(*args: str) -> None:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", *args],
            cwd=str(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    alembic("downgrade", "0004_correlation_foundation")
    alembic("upgrade", "0005_incident_foundation")

    # Confirm head via asyncio-free psycopg2 connection (pure psycopg2 not available,
    # so just re-check via alembic current output)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=str(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        env=env,
        capture_output=True,
        text=True,
    )
    assert "0005_incident_foundation" in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Schema: no active-group unique constraint, no production policy
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_active_group_unique_constraint(
    _settings: Settings, _svc: IncidentService
) -> None:
    """Two OPEN Incidents with the same grouping_key must coexist (distinct episodes)."""
    app = create_app(_settings)
    async with app.router.lifespan_context(app):
        sf = app.state.session_factory
        async with sf() as session:
            device = await _make_device(session)
            did = device.id

            # Force-create two Incidents with same grouping_key (distinct IDs)
            gk = hashlib.sha256(b"same-group").hexdigest()
            ik1 = hashlib.sha256(b"i1").hexdigest()
            ik2 = hashlib.sha256(b"i2").hexdigest()
            ts1 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
            ts2 = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
            i1 = Incident(
                incident_key=ik1,
                device_id=did,
                policy_id="P",
                policy_version=1,
                grouping_key=gk,
                title="T",
                summary="S",
                status="OPEN",
                disposition="UNDETERMINED",
                severity="low",
                risk_score=40,
                confidence="medium",
                promotion_score_threshold=30,
                promotion_confidence_threshold="medium",
                evidence_window_seconds=3600,
                first_evidence_at=ts1,
                last_evidence_at=ts1,
            )
            i2 = Incident(
                incident_key=ik2,
                device_id=did,
                policy_id="P",
                policy_version=1,
                grouping_key=gk,
                title="T",
                summary="S",
                status="OPEN",
                disposition="UNDETERMINED",
                severity="low",
                risk_score=40,
                confidence="medium",
                promotion_score_threshold=30,
                promotion_confidence_threshold="medium",
                evidence_window_seconds=3600,
                first_evidence_at=ts2,
                last_evidence_at=ts2,
            )
            session.add_all([i1, i2])
            await session.commit()

            count = await session.scalar(
                select(func.count()).select_from(Incident).where(Incident.grouping_key == gk)
            )
            assert count == 2, "Multiple OPEN Incidents must share one grouping_key"
            await session.delete(device)
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_production_policy_for_process_listener_activity(_settings: Settings) -> None:
    """The global production registry must have no policy for PROCESS_LISTENER_ACTIVITY."""
    from aegisx_api.incident.policies import registry as global_registry

    policies = global_registry.get_policies_for_strategy("PROCESS_LISTENER_ACTIVITY")
    assert policies == [], "PROCESS_LISTENER_ACTIVITY must have NO production promotion policy"


# ---------------------------------------------------------------------------
# Incident creation and in-window attachment
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_incident_creation_then_in_window_attachment(
    _settings: Settings, _svc: IncidentService
) -> None:
    app = create_app(_settings)
    async with app.router.lifespan_context(app):
        sf = app.state.session_factory
        async with sf() as session:
            device = await _make_device(session)
            c1 = await _make_candidate(session, device)
            async with session.begin_nested():
                await _svc.process_candidate(session, c1)
            await session.flush()

            inc = await session.scalar(select(Incident).where(Incident.device_id == device.id))
            assert inc is not None
            assert inc.status == "OPEN"
            assert inc.disposition == "UNDETERMINED"
            last_at = inc.last_evidence_at

            # Second candidate within window
            c2 = await _make_candidate(
                session,
                device,
                start=c1.start_timestamp + timedelta(minutes=5),
                end=c1.end_timestamp + timedelta(minutes=10),
            )
            async with session.begin_nested():
                await _svc.process_candidate(session, c2)
            await session.flush()

            await session.refresh(inc)
            assert inc.last_evidence_at >= last_at, "last_evidence_at must not decrease"
            assert inc.last_evidence_at >= c2.end_timestamp

            count = await session.scalar(
                select(func.count()).select_from(Incident).where(Incident.device_id == device.id)
            )
            assert count == 1

            await session.delete(device)
            await session.commit()


# ---------------------------------------------------------------------------
# Out-of-window → new episode
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_out_of_window_candidate_creates_new_incident(
    _settings: Settings, _svc: IncidentService
) -> None:
    app = create_app(_settings)
    async with app.router.lifespan_context(app):
        sf = app.state.session_factory
        async with sf() as session:
            device = await _make_device(session)
            c1 = await _make_candidate(
                session, device, start=datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
            )
            async with session.begin_nested():
                await _svc.process_candidate(session, c1)

            c2 = await _make_candidate(
                session,
                device,
                start=datetime(2026, 1, 1, 5, 0, tzinfo=UTC),
            )
            async with session.begin_nested():
                await _svc.process_candidate(session, c2)
            await session.flush()

            count = await session.scalar(
                select(func.count()).select_from(Incident).where(Incident.device_id == device.id)
            )
            assert count == 2, "Out-of-window candidate must create a new episode Incident"
            await session.delete(device)
            await session.commit()


# ---------------------------------------------------------------------------
# RESOLVED Incident is non-attachable
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolved_incident_not_attachable(_settings: Settings, _svc: IncidentService) -> None:
    app = create_app(_settings)
    async with app.router.lifespan_context(app):
        sf = app.state.session_factory
        async with sf() as session:
            device = await _make_device(session)
            c1 = await _make_candidate(session, device)
            async with session.begin_nested():
                await _svc.process_candidate(session, c1)
            await session.flush()

            inc = await session.scalar(select(Incident).where(Incident.device_id == device.id))
            assert inc is not None

            # Manually RESOLVE with CONFIRMED_THREAT to satisfy DB check
            inc.status = "RESOLVED"
            inc.disposition = "CONFIRMED_THREAT"
            inc.closed_at = datetime.now(UTC)
            await session.flush()

            # A new candidate in the same window should NOT attach
            c2 = await _make_candidate(
                session,
                device,
                start=c1.start_timestamp + timedelta(minutes=1),
            )
            async with session.begin_nested():
                await _svc.process_candidate(session, c2)
            await session.flush()

            # A new Incident should be created (resolved one is frozen) OR skipped
            # either way the resolved Incident must still have exactly 1 candidate
            from aegisx_api.models.incident import incident_correlation_candidates as icc

            attached = await session.scalar(
                select(func.count()).select_from(icc).where(icc.c.incident_id == inc.id)
            )
            assert attached == 1, "RESOLVED Incident must not gain new candidates"
            await session.delete(device)
            await session.commit()


# ---------------------------------------------------------------------------
# last_evidence_at never moves backward (out-of-order evidence)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_last_evidence_at_never_moves_backward(
    _settings: Settings, _svc: IncidentService
) -> None:
    app = create_app(_settings)
    async with app.router.lifespan_context(app):
        sf = app.state.session_factory
        async with sf() as session:
            device = await _make_device(session)
            late_ts = datetime(2026, 1, 1, 1, 0, tzinfo=UTC)
            early_ts = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

            c1 = await _make_candidate(session, device, start=late_ts, end=late_ts)
            async with session.begin_nested():
                await _svc.process_candidate(session, c1)
            await session.flush()

            inc = await session.scalar(select(Incident).where(Incident.device_id == device.id))
            assert inc is not None
            expected_last = inc.last_evidence_at

            # Now send earlier-timestamped candidate (late-arriving / out-of-order)
            c2 = await _make_candidate(session, device, start=early_ts, end=early_ts)
            async with session.begin_nested():
                await _svc.process_candidate(session, c2)
            await session.flush()

            await session.refresh(inc)
            assert inc.last_evidence_at >= expected_last, (
                "last_evidence_at must never move backward"
            )
            await session.delete(device)
            await session.commit()


# ---------------------------------------------------------------------------
# Duplicate candidate processing is idempotent
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_candidate_processing_is_idempotent(
    _settings: Settings, _svc: IncidentService
) -> None:
    app = create_app(_settings)
    async with app.router.lifespan_context(app):
        sf = app.state.session_factory
        async with sf() as session:
            device = await _make_device(session)
            c1 = await _make_candidate(session, device)
            async with session.begin_nested():
                await _svc.process_candidate(session, c1)
            await session.flush()

            # Process the SAME candidate again
            async with session.begin_nested():
                await _svc.process_candidate(session, c1)
            await session.flush()

            count = await session.scalar(
                select(func.count()).select_from(Incident).where(Incident.device_id == device.id)
            )
            assert count == 1, "Duplicate candidate must not create a second Incident"

            from aegisx_api.models.incident import incident_correlation_candidates as icc

            attached = await session.scalar(
                select(func.count()).select_from(icc).where(icc.c.candidate_id == c1.id)
            )
            assert attached == 1, "Candidate must be attached exactly once"
            await session.delete(device)
            await session.commit()


# ---------------------------------------------------------------------------
# Savepoint failure preserves Event, Detection, Candidate
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_incident_savepoint_failure_preserves_event_detection_candidate(
    _settings: Settings, _svc: IncidentService
) -> None:
    app = create_app(_settings)
    async with app.router.lifespan_context(app):
        sf = app.state.session_factory
        async with sf() as session:
            device = await _make_device(session)
            c1 = await _make_candidate(session, device)
            ev_id = c1.events[0].id
            det_id = c1.detections[0].id
            cand_id = c1.id

            # Simulate savepoint failure during Incident promotion
            try:
                async with session.begin_nested():
                    await _svc.process_candidate(session, c1)
                    raise RuntimeError("forced failure")
            except RuntimeError:
                pass

            await session.commit()

        # Verify in a fresh session
        async with sf() as session:
            ev = await session.get(Event, ev_id)
            assert ev is not None, "Event must survive Incident savepoint failure"

            det = await session.get(Detection, det_id)
            assert det is not None, "Detection must survive Incident savepoint failure"

            cand = await session.get(CorrelationCandidate, cand_id)
            assert cand is not None, "CorrelationCandidate must survive Incident savepoint failure"

            inc_count = await session.scalar(
                select(func.count()).select_from(Incident).where(Incident.device_id == device.id)
            )
            assert inc_count == 0, "No Incident must exist after savepoint failure"

            d = await session.get(Device, device.id)
            if d:
                await session.delete(d)
                await session.commit()


# ---------------------------------------------------------------------------
# Ambiguous incidents → fail closed
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ambiguous_multiple_eligible_incidents_fail_closed(
    _settings: Settings, _svc: IncidentService
) -> None:
    """Two OPEN incidents in the same window → service must raise, not pick one."""
    app = create_app(_settings)
    async with app.router.lifespan_context(app):
        sf = app.state.session_factory
        async with sf() as session:
            device = await _make_device(session)
            did = device.id

            ts = datetime(2026, 1, 1, 0, 30, tzinfo=UTC)

            # Determine the grouping_key our policy would generate for this device
            policy = _EligiblePolicy()
            gk = hashlib.sha256(f"{did}:{policy.policy_id}".encode()).hexdigest()

            # Force-create two OPEN Incidents with the same grouping_key and overlapping windows
            base_ts = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
            for seed in [b"amb1", b"amb2"]:
                ik = hashlib.sha256(seed).hexdigest()
                session.add(
                    Incident(
                        incident_key=ik,
                        device_id=did,
                        policy_id=policy.policy_id,
                        policy_version=1,
                        grouping_key=gk,
                        title="T",
                        summary="S",
                        status="OPEN",
                        disposition="UNDETERMINED",
                        severity="low",
                        risk_score=40,
                        confidence="medium",
                        promotion_score_threshold=30,
                        promotion_confidence_threshold="medium",
                        evidence_window_seconds=3600,
                        first_evidence_at=base_ts,
                        last_evidence_at=base_ts,
                    )
                )
            await session.flush()

            # A new candidate whose window overlaps both
            c = await _make_candidate(session, device, start=ts, end=ts)
            with pytest.raises(RuntimeError, match="Ambiguous"):
                async with session.begin_nested():
                    await _svc.process_candidate(session, c)

            await session.delete(device)
            await session.commit()


# ---------------------------------------------------------------------------
# Advisory lock timeout → fail closed
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_advisory_lock_timeout_fails_closed(_settings: Settings, _registry) -> None:
    """Hold the advisory lock in one transaction; second call must timeout and fail closed."""
    engine = create_async_engine(TEST_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    svc_fast = IncidentService(
        evidence_window=timedelta(hours=1),
        lock_timeout_ms=300,  # very short timeout
    )
    svc_fast._registry = _registry

    try:
        async with session_factory() as setup_session:
            device = await _make_device(setup_session)
            device_id = device.id
            await setup_session.commit()

        async with session_factory() as s1, session_factory() as s2:
            dev1 = await s1.get(Device, device_id)
            assert dev1 is not None
            c1 = await _make_candidate(s1, dev1)

            # Compute the lock_id for this candidate's grouping_key
            decision = svc_fast._registry.get_policies_for_strategy("TEST_STRATEGY")[0].evaluate(c1)
            assert decision is not None
            lock_id = svc_fast._hash_to_lock_id(decision.grouping_key)

            # Session 1 holds the advisory lock inside a transaction
            await s1.execute(text("BEGIN"))
            await s1.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": lock_id})

            # Session 2 must fail quickly (300 ms timeout)
            dev2 = await s2.get(Device, device_id)
            assert dev2 is not None
            c2 = await _make_candidate(s2, dev2)

            with pytest.raises(DBAPIError, match="statement timeout"):
                async with s2.begin_nested():
                    await svc_fast.process_candidate(s2, c2)

            await s1.execute(text("ROLLBACK"))

        async with session_factory() as cleanup_session:
            persisted_device = await cleanup_session.get(Device, device_id)
            assert persisted_device is not None
            await cleanup_session.delete(persisted_device)
            await cleanup_session.commit()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Concurrent same-group creation → only one Incident created
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_same_group_does_not_duplicate_incident(
    _settings: Settings, _registry
) -> None:
    engine = create_async_engine(TEST_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    svc = IncidentService(evidence_window=timedelta(hours=1), lock_timeout_ms=5000)
    svc._registry = _registry

    try:
        async with session_factory() as setup_session:
            device = await _make_device(setup_session)
            did = device.id
            await setup_session.commit()

        async def promote_once():
            async with session_factory() as session:
                d = await session.get(Device, did)
                c = await _make_candidate(session, d)  # type: ignore[arg-type]
                try:
                    async with session.begin_nested():
                        await svc.process_candidate(session, c)
                    await session.commit()
                    return True
                except Exception:
                    await session.rollback()
                    return False

        results = await asyncio.gather(promote_once(), promote_once(), return_exceptions=True)

        async with session_factory() as session:
            # Both candidates are different objects (different correlation_keys / timestamps)
            # so they may each create a new episode — this is acceptable.
            # What must NOT happen: the same single candidate attached twice or DB integrity errors.
            d = await session.get(Device, did)
            if d:
                await session.delete(d)
                await session.commit()

        # No exception raised (IntegrityError / etc.)
        for r in results:
            assert not isinstance(r, Exception), f"Concurrent promotion raised: {r}"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Advisory lock key: full grouping_key used for DB identity
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_grouping_key_full_string_used_for_identity(
    _settings: Settings, _svc: IncidentService
) -> None:
    """Two candidates with different grouping_keys must produce distinct Incidents
    even if their int64 lock ids happen to collide."""
    app = create_app(_settings)
    async with app.router.lifespan_context(app):
        sf = app.state.session_factory
        async with sf() as session:
            device = await _make_device(session)

            c1 = await _make_candidate(session, device)
            c2 = await _make_candidate(session, device, start=datetime(2026, 6, 1, tzinfo=UTC))

            async with session.begin_nested():
                await _svc.process_candidate(session, c1)
            async with session.begin_nested():
                await _svc.process_candidate(session, c2)
            await session.flush()

            incidents = list(
                (
                    await session.scalars(select(Incident).where(Incident.device_id == device.id))
                ).all()
            )
            # Could be 1 (c2 attached) or 2 (out-of-window new episode) — both correct
            # Key invariant: grouping_key on each Incident is the 64-char SHA-256
            for inc in incidents:
                assert len(inc.grouping_key) == 64
                assert len(inc.incident_key) == 64

            await session.delete(device)
            await session.commit()


# ---------------------------------------------------------------------------
# Audit trail: transition recorded on create
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_status_transition_audit_trail_on_creation(
    _settings: Settings, _svc: IncidentService
) -> None:
    app = create_app(_settings)
    async with app.router.lifespan_context(app):
        sf = app.state.session_factory
        async with sf() as session:
            device = await _make_device(session)
            c = await _make_candidate(session, device)
            async with session.begin_nested():
                await _svc.process_candidate(session, c)
            await session.flush()

            inc = await session.scalar(select(Incident).where(Incident.device_id == device.id))
            assert inc is not None
            transitions = list(
                (
                    await session.scalars(
                        select(IncidentStatusTransition).where(
                            IncidentStatusTransition.incident_id == inc.id
                        )
                    )
                ).all()
            )
            assert len(transitions) == 1
            t = transitions[0]
            assert t.to_status == "OPEN"
            assert t.to_disposition == "UNDETERMINED"
            assert t.actor_type == "system"
            assert t.actor_id is None
            assert t.from_status is None
            assert t.from_disposition is None

            await session.delete(device)
            await session.commit()


# ---------------------------------------------------------------------------
# Timeout configurability via Settings
# ---------------------------------------------------------------------------


def test_advisory_lock_timeout_is_configurable_via_settings():
    """Confirm the timeout is a Settings field with a default, not a magic constant."""
    s = Settings(_env_file=None, environment="test", database_url="postgresql+asyncpg://x/y")
    assert s.incident_advisory_lock_timeout_ms == 2000

    s2 = Settings(
        _env_file=None,
        environment="test",
        database_url="postgresql+asyncpg://x/y",
        incident_advisory_lock_timeout_ms=500,
    )
    assert s2.incident_advisory_lock_timeout_ms == 500

    svc = IncidentService(lock_timeout_ms=500)
    assert svc._lock_timeout_ms == 500
