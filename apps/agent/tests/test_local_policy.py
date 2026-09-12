from datetime import UTC, datetime, timedelta

from aegisx_agent.events import NormalizedEvent
from aegisx_agent.local_policy import (
    LOCAL_POLICY_VERSION,
    DeliveryState,
    EventPriority,
    calculate_payload_hash,
    canonical_event_json,
    classify_event,
    retention_for,
)


def _event() -> NormalizedEvent:
    return NormalizedEvent(
        id="00000000-0000-0000-0000-000000000001",
        timestamp=datetime(2026, 9, 12, 12, tzinfo=UTC),
        event_type="system.status",
        source="test",
        severity_hint="normal",
        data={"z": 2, "a": 1},
        metadata={},
    )


def test_local_policy_classifies_known_families_and_fails_closed() -> None:
    assert LOCAL_POLICY_VERSION == 1
    assert classify_event("process.resource_usage") is EventPriority.BULK
    assert classify_event("network.listener_observed") is EventPriority.BULK
    assert classify_event("system.status") is EventPriority.OPERATIONAL
    assert classify_event("process.started") is EventPriority.SECURITY
    assert classify_event("network.connection_closed") is EventPriority.SECURITY
    assert classify_event("future.event") is EventPriority.UNCLASSIFIED
    assert retention_for(EventPriority.BULK) == timedelta(hours=24)
    assert retention_for(EventPriority.OPERATIONAL) == timedelta(days=7)
    assert retention_for(EventPriority.SECURITY) == timedelta(days=30)
    assert retention_for(EventPriority.UNCLASSIFIED) is None


def test_delivery_states_are_transport_only_values() -> None:
    assert [state.value for state in DeliveryState] == ["PENDING", "ACKED", "QUARANTINED"]


def test_canonical_event_json_is_stable_sorted_and_compact() -> None:
    assert canonical_event_json(_event()) == (
        '{"data":{"a":1,"z":2},"event_type":"system.status",'
        '"id":"00000000-0000-0000-0000-000000000001","metadata":{},'
        '"schema_version":1,"severity_hint":"normal","source":"test",'
        '"timestamp":"2026-09-12T12:00:00Z"}'
    )


def test_payload_hash_changes_when_canonical_payload_changes() -> None:
    payload = canonical_event_json(_event())

    assert calculate_payload_hash(payload) == (
        "bb29dd12c8838db7192e91b5e8a40b35a966314176ce4e4c85ef6601b4817dfc"
    )
    assert calculate_payload_hash(payload + " ") != calculate_payload_hash(payload)
