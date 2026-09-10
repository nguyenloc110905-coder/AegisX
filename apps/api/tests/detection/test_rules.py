from datetime import UTC, datetime
from uuid import uuid4

from aegisx_api.detection.defaults import create_default_engine
from aegisx_api.detection.rules.listener_opened import ListenerOpenedRule
from aegisx_api.detection.rules.process_started import ProcessStartedRule
from aegisx_api.models.event import Event


def event(event_type: str, data: dict) -> Event:
    return Event(
        id=uuid4(),
        device_id=uuid4(),
        schema_version=1,
        timestamp=datetime.now(UTC),
        event_type=event_type,
        source="test",
        severity_hint="normal",
        data=data,
        metadata_={},
    )


def test_process_started_rule_matches_verified_transition() -> None:
    source = event("process.started", {"pid": 42, "name": "python"})

    match = ProcessStartedRule().evaluate(source)

    assert match is not None
    assert match.reason == "Process python (PID 42) was newly observed after the process baseline."
    assert match.evidence_event_ids == (source.id,)
    assert ProcessStartedRule.severity == "informational"
    assert ProcessStartedRule.score_contribution == 0


def test_process_started_rule_ignores_irrelevant_or_malformed_event() -> None:
    rule = ProcessStartedRule()

    assert rule.evaluate(event("system.status", {"pid": 42, "name": "python"})) is None
    assert rule.evaluate(event("process.started", {"pid": "bad", "name": "python"})) is None


def test_listener_opened_rule_matches_proved_transition() -> None:
    source = event(
        "network.listener_opened",
        {"protocol": "tcp", "local_ip": "127.0.0.1", "local_port": 8000, "pid": 42},
    )

    match = ListenerOpenedRule().evaluate(source)

    assert match is not None
    assert match.reason == (
        "TCP listener appeared at 127.0.0.1:8000 (PID 42) between complete snapshots."
    )
    assert match.evidence_event_ids == (source.id,)
    assert ListenerOpenedRule.severity == "low"
    assert ListenerOpenedRule.score_contribution == 5


def test_listener_opened_rule_ignores_irrelevant_or_malformed_event() -> None:
    rule = ListenerOpenedRule()

    assert rule.evaluate(event("network.connection_observed", {})) is None
    assert rule.evaluate(event("network.listener_opened", {"local_port": "bad"})) is None


def test_default_engine_does_not_detect_listener_snapshot() -> None:
    source = event(
        "network.listener_observed",
        {"protocol": "tcp", "local_ip": "127.0.0.1", "local_port": 8000, "pid": 42},
    )

    assert create_default_engine().evaluate(source) == []


def test_python_development_listener_open_is_only_a_low_risk_transition() -> None:
    source = event(
        "network.listener_opened",
        {
            "protocol": "tcp",
            "local_ip": "127.0.0.1",
            "local_port": 8000,
            "pid": 4242,
            "process_name": "python",
        },
    )

    match = ListenerOpenedRule().evaluate(source)

    assert match is not None
    assert ListenerOpenedRule.severity == "low"
    assert ListenerOpenedRule.score_contribution == 5
    assert "malware" not in match.reason.lower()
    assert "suspicious" not in match.reason.lower()
