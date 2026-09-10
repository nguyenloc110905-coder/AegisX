from datetime import UTC, datetime, timedelta
from uuid import UUID

from aegisx_api.correlation.strategies.process_listener_activity import (
    ProcessListenerActivityStrategy,
)

from .factories import detection, event

DEVICE_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_DEVICE_ID = UUID("22222222-2222-2222-2222-222222222222")
PROCESS_EVENT_ID = UUID("33333333-3333-3333-3333-333333333333")
LISTENER_EVENT_ID = UUID("44444444-4444-4444-4444-444444444444")
PROCESS_DETECTION_ID = UUID("55555555-5555-5555-5555-555555555555")
LISTENER_DETECTION_ID = UUID("66666666-6666-6666-6666-666666666666")
PROCESS_TIMESTAMP = datetime(2026, 9, 3, 1, 0, tzinfo=UTC)
LISTENER_TIMESTAMP = datetime(2026, 9, 3, 1, 2, tzinfo=UTC)
STARTED_AT = "2026-09-03T01:00:00+00:00"
WINDOW = timedelta(minutes=5)


def process_detection(
    *,
    device_id: UUID = DEVICE_ID,
    pid: int = 4242,
    timestamp: datetime = PROCESS_TIMESTAMP,
    started_at: object = STARTED_AT,
    event_id: UUID = PROCESS_EVENT_ID,
    detection_id: UUID = PROCESS_DETECTION_ID,
    score_contribution: int = 0,
):
    return detection(
        rule_id="PROCESS_STARTED",
        source_event=event(
            event_type="process.started",
            device_id=device_id,
            event_id=event_id,
            timestamp=timestamp,
            data={"pid": pid, "started_at": started_at},
        ),
        score_contribution=score_contribution,
        detection_id=detection_id,
    )


def listener_detection(
    *,
    device_id: UUID = DEVICE_ID,
    pid: int = 4242,
    timestamp: datetime = LISTENER_TIMESTAMP,
    event_id: UUID = LISTENER_EVENT_ID,
    detection_id: UUID = LISTENER_DETECTION_ID,
    score_contribution: int = 5,
):
    return detection(
        rule_id="LISTENER_OPENED",
        source_event=event(
            event_type="network.listener_opened",
            device_id=device_id,
            event_id=event_id,
            timestamp=timestamp,
            data={"pid": pid},
        ),
        score_contribution=score_contribution,
        detection_id=detection_id,
    )


def test_correlates_recent_listener_with_same_process_identity() -> None:
    result = ProcessListenerActivityStrategy().evaluate(
        (process_detection(), listener_detection()), WINDOW
    )

    assert len(result) == 1
    candidate = result[0]
    assert candidate.correlation_key == (
        "61c50a3510e881696424af7566716fc7aed3113a0f6786294bbb066c0eb92c37"
    )
    assert candidate.device_id == DEVICE_ID
    assert candidate.strategy_id == "PROCESS_LISTENER_ACTIVITY"
    assert candidate.start_timestamp == PROCESS_TIMESTAMP
    assert candidate.end_timestamp == LISTENER_TIMESTAMP
    assert candidate.confidence == "low"
    assert candidate.aggregate_score == 5
    assert candidate.detection_ids == (PROCESS_DETECTION_ID, LISTENER_DETECTION_ID)
    assert candidate.event_ids == (PROCESS_EVENT_ID, LISTENER_EVENT_ID)


def test_canonicalizes_equivalent_started_at_instants_regardless_of_evidence_order() -> None:
    utc_process = process_detection(
        event_id=UUID("77777777-7777-7777-7777-777777777777"),
        detection_id=UUID("88888888-8888-8888-8888-888888888888"),
    )
    offset_process = process_detection(
        started_at="2026-09-03T08:00:00+07:00",
        event_id=UUID("99999999-9999-9999-9999-999999999999"),
        detection_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )
    listener = listener_detection()
    strategy = ProcessListenerActivityStrategy()

    utc_key = strategy.evaluate((utc_process, listener), WINDOW)[0].correlation_key
    offset_key = strategy.evaluate((offset_process, listener), WINDOW)[0].correlation_key
    forward_keys = tuple(
        result.correlation_key
        for result in strategy.evaluate((utc_process, offset_process, listener), WINDOW)
    )
    reversed_keys = tuple(
        result.correlation_key
        for result in strategy.evaluate((offset_process, utc_process, listener), WINDOW)
    )

    assert utc_key == "61c50a3510e881696424af7566716fc7aed3113a0f6786294bbb066c0eb92c37"
    assert offset_key == utc_key
    assert forward_keys == (utc_key,)
    assert reversed_keys == forward_keys


def test_returns_no_result_for_different_device_or_pid() -> None:
    strategy = ProcessListenerActivityStrategy()

    assert (
        strategy.evaluate(
            (process_detection(), listener_detection(device_id=OTHER_DEVICE_ID)), WINDOW
        )
        == ()
    )
    assert strategy.evaluate((process_detection(), listener_detection(pid=4040)), WINDOW) == ()


def test_returns_no_result_for_listener_snapshot_without_transition_evidence() -> None:
    observed = detection(
        rule_id="LISTENER_OBSERVED",
        source_event=event(
            event_type="network.listener_observed",
            device_id=DEVICE_ID,
            event_id=LISTENER_EVENT_ID,
            timestamp=LISTENER_TIMESTAMP,
            data={"pid": 4242},
        ),
        score_contribution=5,
        detection_id=LISTENER_DETECTION_ID,
    )

    assert ProcessListenerActivityStrategy().evaluate((process_detection(), observed), WINDOW) == ()


def test_returns_no_result_when_listener_precedes_process() -> None:
    assert (
        ProcessListenerActivityStrategy().evaluate(
            (
                process_detection(),
                listener_detection(timestamp=PROCESS_TIMESTAMP - timedelta(seconds=1)),
            ),
            WINDOW,
        )
        == ()
    )


def test_returns_no_result_when_process_started_at_is_missing_or_invalid() -> None:
    strategy = ProcessListenerActivityStrategy()

    assert (
        strategy.evaluate((process_detection(started_at=None), listener_detection()), WINDOW) == ()
    )
    assert (
        strategy.evaluate(
            (process_detection(started_at="not-a-timestamp"), listener_detection()), WINDOW
        )
        == ()
    )


def test_returns_no_result_when_process_is_outside_window() -> None:
    assert (
        ProcessListenerActivityStrategy().evaluate(
            (
                process_detection(
                    timestamp=LISTENER_TIMESTAMP - timedelta(minutes=5, microseconds=1)
                ),
                listener_detection(),
            ),
            WINDOW,
        )
        == ()
    )


def test_correlates_process_at_exact_inclusive_window_boundary() -> None:
    result = ProcessListenerActivityStrategy().evaluate(
        (
            process_detection(timestamp=LISTENER_TIMESTAMP - WINDOW),
            listener_detection(),
        ),
        WINDOW,
    )

    assert len(result) == 1


def test_counts_duplicate_detection_id_once_in_aggregate_score() -> None:
    duplicate_detection_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    result = ProcessListenerActivityStrategy().evaluate(
        (
            process_detection(detection_id=duplicate_detection_id, score_contribution=60),
            listener_detection(detection_id=duplicate_detection_id, score_contribution=60),
        ),
        WINDOW,
    )

    assert result[0].detection_ids == (duplicate_detection_id,)
    assert result[0].aggregate_score == 60


def test_clamps_aggregate_score_at_100() -> None:
    result = ProcessListenerActivityStrategy().evaluate(
        (
            process_detection(score_contribution=60),
            listener_detection(score_contribution=60),
        ),
        WINDOW,
    )

    assert result[0].aggregate_score == 100


def test_returns_no_result_when_two_process_identities_are_eligible() -> None:
    later_process = process_detection(
        timestamp=PROCESS_TIMESTAMP + timedelta(minutes=1),
        started_at="2026-09-03T01:01:00+00:00",
        event_id=UUID("77777777-7777-7777-7777-777777777777"),
        detection_id=UUID("88888888-8888-8888-8888-888888888888"),
    )

    assert (
        ProcessListenerActivityStrategy().evaluate(
            (process_detection(), later_process, listener_detection()), WINDOW
        )
        == ()
    )


def test_ignores_old_pid_reuse_outside_window_when_current_identity_matches() -> None:
    old_process = process_detection(
        timestamp=LISTENER_TIMESTAMP - timedelta(minutes=5, microseconds=1),
        started_at="2026-09-03T00:00:00+00:00",
        event_id=UUID("99999999-9999-9999-9999-999999999999"),
        detection_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )
    current_process = process_detection()

    result = ProcessListenerActivityStrategy().evaluate(
        (old_process, current_process, listener_detection()), WINDOW
    )

    assert len(result) == 1
    assert result[0].detection_ids == (PROCESS_DETECTION_ID, LISTENER_DETECTION_ID)
