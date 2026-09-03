from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import UUID

from aegisx_api.correlation.types import CorrelationResult
from aegisx_api.models.detection import Detection
from aegisx_api.models.event import Event


@dataclass(frozen=True)
class _ProcessEvidence:
    detection: Detection
    event: Event
    pid: int
    started_at: datetime

    @property
    def identity(self) -> tuple[UUID, int, datetime]:
        return (self.detection.device_id, self.pid, self.started_at)


@dataclass(frozen=True)
class _ListenerEvidence:
    detection: Detection
    event: Event
    pid: int


class ProcessListenerActivityStrategy:
    strategy_id = "PROCESS_LISTENER_ACTIVITY"
    name = "Process activity with observed listener"
    description = "Associates a listener snapshot with a recently started process identity."
    required_rule_ids = frozenset({"PROCESS_STARTED", "LISTENER_OBSERVED"})

    def evaluate(
        self, evidence: Sequence[Detection], window: timedelta
    ) -> tuple[CorrelationResult, ...]:
        processes = tuple(
            process
            for detection in evidence
            if (process := self._process_evidence(detection)) is not None
        )
        listeners = tuple(
            listener
            for detection in evidence
            if (listener := self._listener_evidence(detection)) is not None
        )
        earliest_listener_by_identity: dict[tuple[UUID, int, datetime], _ListenerEvidence] = {}
        process_by_identity: dict[tuple[UUID, int, datetime], _ProcessEvidence] = {}

        for listener in sorted(listeners, key=lambda item: (item.event.timestamp, item.event.id)):
            eligible = [
                process for process in processes if self._is_eligible(process, listener, window)
            ]
            identities = {process.identity for process in eligible}
            if len(identities) != 1:
                continue
            identity = next(iter(identities))
            selected_process = min(
                (process for process in eligible if process.identity == identity),
                key=lambda item: (item.event.timestamp, item.event.id),
            )
            earliest_listener_by_identity.setdefault(identity, listener)
            process_by_identity.setdefault(identity, selected_process)

        results = (
            self._result(process_by_identity[identity], listener, identity)
            for identity, listener in earliest_listener_by_identity.items()
        )
        return tuple(sorted(results, key=lambda result: result.correlation_key))

    def _process_evidence(self, detection: Detection) -> _ProcessEvidence | None:
        if detection.rule_id != "PROCESS_STARTED":
            return None
        event = detection.source_event
        pid = self._positive_pid(event.data.get("pid"))
        started_at = self._started_at(event.data.get("started_at"))
        if pid is None or started_at is None:
            return None
        return _ProcessEvidence(detection=detection, event=event, pid=pid, started_at=started_at)

    def _listener_evidence(self, detection: Detection) -> _ListenerEvidence | None:
        if detection.rule_id != "LISTENER_OBSERVED":
            return None
        event = detection.source_event
        pid = self._positive_pid(event.data.get("pid"))
        if pid is None:
            return None
        return _ListenerEvidence(detection=detection, event=event, pid=pid)

    @staticmethod
    def _positive_pid(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
        return value

    @staticmethod
    def _started_at(value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            started_at = datetime.fromisoformat(value)
        except ValueError:
            return None
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            return None
        return started_at

    @staticmethod
    def _is_eligible(
        process: _ProcessEvidence, listener: _ListenerEvidence, window: timedelta
    ) -> bool:
        if (
            process.detection.device_id != listener.detection.device_id
            or process.pid != listener.pid
        ):
            return False
        try:
            elapsed = listener.event.timestamp - process.event.timestamp
        except TypeError:
            return False
        return timedelta() <= elapsed <= window

    def _result(
        self,
        process: _ProcessEvidence,
        listener: _ListenerEvidence,
        identity: tuple[UUID, int, datetime],
    ) -> CorrelationResult:
        detection_ids = self._unique_ids((process.detection.id, listener.detection.id))
        event_ids = self._unique_ids((process.event.id, listener.event.id))
        identity_device_id, pid, started_at = identity
        canonical_identity = (
            f"{self.strategy_id}|{identity_device_id}|{pid}|{started_at.isoformat()}"
        )
        return CorrelationResult(
            correlation_key=sha256(canonical_identity.encode()).hexdigest(),
            device_id=identity_device_id,
            strategy_id=self.strategy_id,
            start_timestamp=process.event.timestamp,
            end_timestamp=listener.event.timestamp,
            confidence="low",
            aggregate_score=min(
                100,
                sum(
                    detection.score_contribution
                    for detection in self._unique_detections(
                        (process.detection, listener.detection)
                    )
                ),
            ),
            detection_ids=detection_ids,
            event_ids=event_ids,
        )

    @staticmethod
    def _unique_ids(ids: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return tuple(dict.fromkeys(ids))

    @staticmethod
    def _unique_detections(detections: tuple[Detection, ...]) -> tuple[Detection, ...]:
        by_id = {detection.id: detection for detection in detections}
        return tuple(by_id.values())
