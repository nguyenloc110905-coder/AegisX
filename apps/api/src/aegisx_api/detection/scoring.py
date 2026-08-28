from collections.abc import Iterable

from aegisx_api.detection.types import DetectionResult


def calculate_risk_score(results: Iterable[DetectionResult]) -> int:
    total = 0
    for result in results:
        if result.score_contribution < 0:
            raise ValueError("score contributions must be non-negative")
        total += result.score_contribution
    return min(100, total)
