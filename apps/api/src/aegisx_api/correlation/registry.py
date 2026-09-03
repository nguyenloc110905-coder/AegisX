from collections import defaultdict
from collections.abc import Iterable

from aegisx_api.correlation.strategies.base import CorrelationStrategy


class CorrelationRegistry:
    def __init__(self, strategies: Iterable[CorrelationStrategy]) -> None:
        by_rule_id: dict[str, list[CorrelationStrategy]] = defaultdict(list)
        ordered_strategies: list[CorrelationStrategy] = []
        seen_ids: set[str] = set()
        for strategy in strategies:
            if strategy.strategy_id in seen_ids:
                raise ValueError(f"duplicate strategy ID: {strategy.strategy_id}")
            seen_ids.add(strategy.strategy_id)
            ordered_strategies.append(strategy)
            for rule_id in strategy.required_rule_ids:
                by_rule_id[rule_id].append(strategy)
        self._by_rule_id = {
            rule_id: tuple(indexed_strategies) for rule_id, indexed_strategies in by_rule_id.items()
        }
        self._strategies = tuple(ordered_strategies)

    def strategies_for(self, rule_ids: frozenset[str]) -> tuple[CorrelationStrategy, ...]:
        selected_ids = {
            strategy.strategy_id
            for rule_id in rule_ids
            for strategy in self._by_rule_id.get(rule_id, ())
        }
        return tuple(
            strategy for strategy in self._strategies if strategy.strategy_id in selected_ids
        )
