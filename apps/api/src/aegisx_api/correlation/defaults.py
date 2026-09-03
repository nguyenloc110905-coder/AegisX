from aegisx_api.correlation.engine import CorrelationEngine
from aegisx_api.correlation.registry import CorrelationRegistry
from aegisx_api.correlation.strategies.process_listener_activity import (
    ProcessListenerActivityStrategy,
)


def create_default_correlation_engine() -> CorrelationEngine:
    return CorrelationEngine(CorrelationRegistry([ProcessListenerActivityStrategy()]))
