from dataclasses import replace

import pytest

from aegisx_api.detection.scoring import calculate_risk_score
from aegisx_api.detection.types import DetectionResult

from .test_rules import event


def result(score: int) -> DetectionResult:
    source = event("system.status", {})
    return DetectionResult(
        device_id=source.device_id,
        source_event_id=source.id,
        rule_id="TEST",
        timestamp=source.timestamp,
        severity="low",
        score_contribution=score,
        reason="test",
        evidence_event_ids=(source.id,),
    )


def test_risk_score_sums_contributions_and_clamps_at_100() -> None:
    assert calculate_risk_score([result(5), result(20)]) == 25
    assert calculate_risk_score([result(60), result(50)]) == 100


def test_risk_score_rejects_negative_contribution() -> None:
    negative = replace(result(5), score_contribution=-1)

    with pytest.raises(ValueError, match="score contributions must be non-negative"):
        calculate_risk_score([negative])
