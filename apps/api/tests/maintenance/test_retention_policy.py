from datetime import UTC, datetime, timedelta

import pytest

from aegisx_api.maintenance.retention_policy import (
    RETENTION_POLICY_VERSION,
    RETENTION_RULES,
    RetentionRule,
    cutoff_for,
)


def test_policy_v1_has_exact_event_ttls() -> None:
    assert RETENTION_POLICY_VERSION == 1
    assert {rule.event_type: rule.retention for rule in RETENTION_RULES} == {
        "process.resource_usage": timedelta(hours=24),
        "network.listener_observed": timedelta(hours=24),
        "network.connection_observed": timedelta(hours=24),
        "system.status": timedelta(days=7),
        "process.started": timedelta(days=30),
        "process.exited": timedelta(days=30),
        "network.listener_opened": timedelta(days=30),
        "network.listener_closed": timedelta(days=30),
        "network.connection_opened": timedelta(days=30),
        "network.connection_closed": timedelta(days=30),
    }


def test_cutoff_uses_timezone_aware_evaluation_time() -> None:
    now = datetime(2026, 9, 11, 12, tzinfo=UTC)
    rule = RetentionRule("system.status", timedelta(days=7))

    assert cutoff_for(rule, now) == datetime(2026, 9, 4, 12, tzinfo=UTC)


def test_cutoff_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        cutoff_for(RETENTION_RULES[0], datetime(2026, 9, 11, 12))


@pytest.mark.parametrize("retention", [timedelta(0), timedelta(seconds=-1)])
def test_rule_rejects_non_positive_retention(retention: timedelta) -> None:
    with pytest.raises(ValueError, match="positive"):
        RetentionRule("system.status", retention)
