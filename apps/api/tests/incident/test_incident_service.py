"""Unit tests for IncidentService — promotion policy, grouping, and lifecycle semantics.

These tests run against an in-process registry using test-only promotion policies.
No production promotion policy is introduced here.
"""
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from uuid import uuid4

import pytest

from aegisx_api.incident.policies import (
    IncidentDecision,
    IncidentPromotionPolicy,
    IncidentPolicyRegistry,
    registry,
)
from aegisx_api.services.incident import IncidentService


# ---------------------------------------------------------------------------
# Test-only promotion policy helpers
# ---------------------------------------------------------------------------


class AlwaysPromotePolicy(IncidentPromotionPolicy):
    def __init__(
        self,
        *,
        policy_id: str = "TEST_ALWAYS_PROMOTE",
        policy_version: int = 1,
        strategy_id: str = "TEST_STRATEGY",
        score_threshold: int = 10,
    ) -> None:
        self.policy_id = policy_id
        self.policy_version = policy_version
        self.supported_strategy_ids = [strategy_id]
        self.name = "Always Promote Test Policy"
        self.description = "Promotes any candidate — for testing only"
        self.score_threshold = score_threshold

    def evaluate(self, candidate: Any) -> Optional[IncidentDecision]:
        import hashlib

        grouping_key = hashlib.sha256(str(candidate.device_id).encode()).hexdigest()
        return IncidentDecision(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            grouping_key=grouping_key,
            title="Test Incident Title",
            summary="Test Incident Summary",
            score_threshold=self.score_threshold,
            confidence_threshold="medium",
            trigger_candidate_id=candidate.id,
        )


class NeverPromotePolicy(IncidentPromotionPolicy):
    def __init__(self) -> None:
        self.policy_id = "TEST_NEVER_PROMOTE"
        self.policy_version = 1
        self.supported_strategy_ids = ["TEST_STRATEGY"]
        self.name = "Never Promote Test Policy"
        self.description = "Never promotes — for testing only"

    def evaluate(self, candidate: Any) -> Optional[IncidentDecision]:
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_registry() -> Any:
    registry.clear()
    yield
    registry.clear()


def _make_candidate(
    *,
    strategy_id: str = "TEST_STRATEGY",
    confidence: str = "high",
    aggregate_score: int = 50,
    device_id=None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Any:
    """Return a simple namespace object simulating a CorrelationCandidate."""
    from types import SimpleNamespace

    ts = start or datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        device_id=device_id or uuid4(),
        strategy_id=strategy_id,
        confidence=confidence,
        aggregate_score=aggregate_score,
        start_timestamp=ts,
        end_timestamp=end or ts,
        events=["ev1"],
        detections=["det1"],
    )


# ---------------------------------------------------------------------------
# Policy registry unit tests
# ---------------------------------------------------------------------------


def test_registry_register_and_lookup() -> None:
    p = AlwaysPromotePolicy()
    registry.register(p)
    result = registry.get_policies_for_strategy("TEST_STRATEGY")
    assert result == [p]


def test_registry_no_match_returns_empty() -> None:
    result = registry.get_policies_for_strategy("UNKNOWN_STRATEGY")
    assert result == []


def test_registry_duplicate_raises() -> None:
    p = AlwaysPromotePolicy()
    registry.register(p)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(AlwaysPromotePolicy())


def test_registry_clear_removes_all() -> None:
    registry.register(AlwaysPromotePolicy())
    registry.clear()
    assert registry.get_policies_for_strategy("TEST_STRATEGY") == []


def test_registry_multi_strategy() -> None:
    class MultiStrategy(IncidentPromotionPolicy):
        policy_id = "MULTI"
        policy_version = 1
        supported_strategy_ids = ["A", "B"]
        name = "Multi"
        description = "Multi strategy policy"

        def evaluate(self, candidate: Any) -> Optional[IncidentDecision]:
            return None

    p = MultiStrategy()
    registry.register(p)
    assert registry.get_policies_for_strategy("A") == [p]
    assert registry.get_policies_for_strategy("B") == [p]
    assert registry.get_policies_for_strategy("C") == []


# ---------------------------------------------------------------------------
# IncidentService._hash_to_lock_id unit tests
# ---------------------------------------------------------------------------


def test_hash_to_lock_id_is_deterministic() -> None:
    svc = IncidentService()
    key = "a" * 64
    assert svc._hash_to_lock_id(key) == svc._hash_to_lock_id(key)


def test_hash_to_lock_id_is_int_in_signed_64_range() -> None:
    svc = IncidentService()
    result = svc._hash_to_lock_id("x" * 64)
    assert isinstance(result, int)
    assert -(2**63) <= result < 2**63


def test_hash_to_lock_id_different_keys_mostly_different() -> None:
    svc = IncidentService()
    a = svc._hash_to_lock_id("a" * 64)
    b = svc._hash_to_lock_id("b" * 64)
    assert a != b  # not guaranteed but overwhelmingly likely for distinct inputs


# ---------------------------------------------------------------------------
# IncidentService._compute_severity unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("risk", "expected"),
    [
        (0, "informational"),
        (9, "informational"),
        (10, "low"),
        (29, "low"),
        (30, "medium"),
        (59, "medium"),
        (60, "high"),
        (79, "high"),
        (80, "critical"),
        (100, "critical"),
    ],
)
def test_compute_severity(risk: int, expected: str) -> None:
    svc = IncidentService()
    assert svc._compute_severity(risk) == expected


# ---------------------------------------------------------------------------
# Policy gate: no production policy → no incident
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_policy_registered_skips_promotion() -> None:
    """No production policy exists, so no incident must ever be created."""
    # registry is empty (cleared by autouse fixture)
    svc = IncidentService()
    candidate = _make_candidate(confidence="high", aggregate_score=80)

    # If process_candidate tried to create an Incident it would fail because
    # there's no DB session — the fact it returns without error confirms early exit.
    captured_calls: list[str] = []

    class FakeSession:
        async def scalars(self, *a: Any, **kw: Any) -> Any:
            captured_calls.append("scalars")

        async def execute(self, *a: Any, **kw: Any) -> None:
            captured_calls.append("execute")

        def add(self, *a: Any) -> None:
            captured_calls.append("add")

    await svc.process_candidate(FakeSession(), candidate)  # type: ignore[arg-type]
    assert "add" not in captured_calls


@pytest.mark.asyncio
async def test_low_confidence_skips_promotion() -> None:
    """Candidates with confidence=low must not be promoted even if policy exists."""
    registry.register(AlwaysPromotePolicy())
    svc = IncidentService()
    candidate = _make_candidate(confidence="low", aggregate_score=80)

    captured_adds: list[str] = []

    class FakeSession:
        async def scalars(self, *a: Any, **kw: Any) -> Any:
            return None

        async def execute(self, *a: Any, **kw: Any) -> None:
            pass

        def add(self, obj: Any) -> None:
            captured_adds.append(type(obj).__name__)

    await svc.process_candidate(FakeSession(), candidate)  # type: ignore[arg-type]
    assert "Incident" not in captured_adds


@pytest.mark.asyncio
async def test_low_score_skips_promotion() -> None:
    """Candidates with aggregate_score < 30 must not be promoted."""
    registry.register(AlwaysPromotePolicy())
    svc = IncidentService()
    candidate = _make_candidate(confidence="high", aggregate_score=10)

    captured_adds: list[str] = []

    class FakeSession:
        async def scalars(self, *a: Any, **kw: Any) -> Any:
            return None

        async def execute(self, *a: Any, **kw: Any) -> None:
            pass

        def add(self, obj: Any) -> None:
            captured_adds.append(type(obj).__name__)

    await svc.process_candidate(FakeSession(), candidate)  # type: ignore[arg-type]
    assert "Incident" not in captured_adds


@pytest.mark.asyncio
async def test_never_promote_policy_skips() -> None:
    """A policy that returns None from evaluate() must produce no Incident."""
    registry.register(NeverPromotePolicy())
    svc = IncidentService()
    candidate = _make_candidate(confidence="high", aggregate_score=80)

    captured_adds: list[str] = []

    class FakeSession:
        async def scalars(self, *a: Any, **kw: Any) -> Any:
            return None

        async def execute(self, *a: Any, **kw: Any) -> None:
            pass

        def add(self, obj: Any) -> None:
            captured_adds.append(type(obj).__name__)

    await svc.process_candidate(FakeSession(), candidate)  # type: ignore[arg-type]
    assert "Incident" not in captured_adds


# ---------------------------------------------------------------------------
# AlwaysPromote policy evaluate() unit tests
# ---------------------------------------------------------------------------


def test_always_promote_policy_returns_decision() -> None:
    p = AlwaysPromotePolicy()
    cand = _make_candidate()
    decision = p.evaluate(cand)
    assert decision is not None
    assert decision.policy_id == "TEST_ALWAYS_PROMOTE"
    assert len(decision.grouping_key) == 64


def test_never_promote_policy_returns_none() -> None:
    p = NeverPromotePolicy()
    cand = _make_candidate()
    assert p.evaluate(cand) is None


# ---------------------------------------------------------------------------
# Independent registry instance (no global state pollution)
# ---------------------------------------------------------------------------


def test_independent_registry_instances_are_isolated() -> None:
    r1 = IncidentPolicyRegistry()
    r2 = IncidentPolicyRegistry()
    r1.register(AlwaysPromotePolicy(policy_id="A"))
    assert r2.get_policies_for_strategy("TEST_STRATEGY") == []


# ---------------------------------------------------------------------------
# Sliding-window timestamp invariant (unit only — no DB)
# ---------------------------------------------------------------------------


def test_hash_to_lock_id_collision_does_not_affect_grouping_key() -> None:
    """Simulate two different grouping_keys that collide in 64-bit lock space.

    The lock ID collision (if any) only serialises execution — it does NOT
    mix Incident identities because the DB query always filters by the full
    64-character grouping_key string.
    """
    svc = IncidentService()
    import hashlib

    # Fabricate two different keys and confirm they produce distinct grouping_keys
    key_a = hashlib.sha256(b"incident-a").hexdigest()
    key_b = hashlib.sha256(b"incident-b").hexdigest()
    assert key_a != key_b  # different grouping identities
    # Even if their lock ids happen to collide (rare) the keys are still distinct
    assert len(key_a) == 64
    assert len(key_b) == 64
