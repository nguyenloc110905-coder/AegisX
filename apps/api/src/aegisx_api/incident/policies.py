from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass
class IncidentDecision:
    policy_id: str
    policy_version: int
    grouping_key: str  # 64-character SHA-256
    title: str
    summary: str
    score_threshold: int
    confidence_threshold: str
    trigger_candidate_id: UUID


class IncidentPromotionPolicy(ABC):
    policy_id: str
    policy_version: int
    supported_strategy_ids: list[str]
    name: str
    description: str

    @abstractmethod
    def evaluate(self, candidate: Any) -> IncidentDecision | None:
        pass


class IncidentPolicyRegistry:
    def __init__(self) -> None:
        self._policies_by_strategy: dict[str, list[IncidentPromotionPolicy]] = {}
        self._registered_keys: set[tuple[str, int]] = set()

    def register(self, policy: IncidentPromotionPolicy) -> None:
        key = (policy.policy_id, policy.policy_version)
        if key in self._registered_keys:
            raise ValueError(
                f"Policy {policy.policy_id} v{policy.policy_version} is already registered"
            )

        self._registered_keys.add(key)
        for strategy_id in policy.supported_strategy_ids:
            if strategy_id not in self._policies_by_strategy:
                self._policies_by_strategy[strategy_id] = []
            self._policies_by_strategy[strategy_id].append(policy)

    def get_policies_for_strategy(self, strategy_id: str) -> list[IncidentPromotionPolicy]:
        return self._policies_by_strategy.get(strategy_id, [])

    def clear(self) -> None:
        self._policies_by_strategy.clear()
        self._registered_keys.clear()


# Global registry instance
registry = IncidentPolicyRegistry()
