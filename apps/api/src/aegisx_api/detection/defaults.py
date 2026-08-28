from aegisx_api.detection.engine import DetectionEngine
from aegisx_api.detection.registry import RuleRegistry
from aegisx_api.detection.rules.listener_observed import ListenerObservedRule
from aegisx_api.detection.rules.process_started import ProcessStartedRule


def create_default_engine() -> DetectionEngine:
    return DetectionEngine(RuleRegistry([ProcessStartedRule(), ListenerObservedRule()]))
