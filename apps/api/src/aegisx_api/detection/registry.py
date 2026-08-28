from collections import defaultdict
from collections.abc import Iterable

from aegisx_api.detection.rules.base import DetectionRule


class RuleRegistry:
    def __init__(self, rules: Iterable[DetectionRule]) -> None:
        by_event_type: dict[str, list[DetectionRule]] = defaultdict(list)
        seen_ids: set[str] = set()
        for rule in rules:
            if rule.rule_id in seen_ids:
                raise ValueError(f"duplicate rule ID: {rule.rule_id}")
            seen_ids.add(rule.rule_id)
            for event_type in rule.event_types:
                by_event_type[event_type].append(rule)
        self._by_event_type = {
            event_type: tuple(indexed_rules) for event_type, indexed_rules in by_event_type.items()
        }

    def rules_for(self, event_type: str) -> tuple[DetectionRule, ...]:
        return self._by_event_type.get(event_type, ())
