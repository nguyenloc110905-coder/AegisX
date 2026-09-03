from collections.abc import Sequence
from datetime import UTC, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from aegisx_api.correlation.engine import CorrelationEngine
from aegisx_api.correlation.types import CorrelationResult
from aegisx_api.models.correlation import CorrelationCandidate
from aegisx_api.models.detection import Detection

_RELEVANT_RULE_IDS = ("PROCESS_STARTED", "LISTENER_OBSERVED")
_PROCESS_LISTENER_REASON = (
    "A listener snapshot was associated with the recently started process identity."
)


class CorrelationService:
    def __init__(self, engine: CorrelationEngine) -> None:
        self._engine = engine

    def strategy_ids_for(self, new_detections: Sequence[Detection]) -> tuple[str, ...]:
        return self._engine.strategy_ids_for(new_detections)

    async def correlate(
        self,
        session: AsyncSession,
        device_id: UUID,
        new_detections: Sequence[Detection],
        window: timedelta,
    ) -> Sequence[CorrelationCandidate]:
        if not new_detections:
            return ()

        new_by_id = {detection.id: detection for detection in new_detections}
        new_detection_ids = frozenset(new_by_id)
        timestamp_ranges = tuple(
            and_(
                Detection.timestamp >= timestamp - window,
                Detection.timestamp <= timestamp + window,
            )
            for timestamp in {detection.timestamp for detection in new_detections}
        )
        evidence = list(
            (
                await session.scalars(
                    select(Detection)
                    .options(selectinload(Detection.source_event))
                    .where(
                        Detection.device_id == device_id,
                        Detection.rule_id.in_(_RELEVANT_RULE_IDS),
                        Detection.id.not_in(new_detection_ids),
                        or_(*timestamp_ranges),
                    )
                    .order_by(Detection.timestamp, Detection.id)
                )
            ).all()
        )
        evidence_by_id = {detection.id: detection for detection in evidence}
        evidence_by_id.update(new_by_id)
        complete_evidence = tuple(evidence_by_id.values())
        self._restore_utc_timezone(complete_evidence)

        results_by_key: dict[str, CorrelationResult] = {}
        for anchor in sorted(new_by_id.values(), key=lambda item: (item.timestamp, item.id)):
            anchor_evidence = self._evidence_for_anchor(anchor, complete_evidence)
            for result in self._engine.evaluate((anchor,), anchor_evidence, window):
                if anchor.id in result.detection_ids:
                    results_by_key.setdefault(result.correlation_key, result)
        results = tuple(results_by_key.values())
        if not results:
            return ()

        result_keys = tuple(result.correlation_key for result in results)
        existing_keys = set(
            (
                await session.scalars(
                    select(CorrelationCandidate.correlation_key).where(
                        CorrelationCandidate.correlation_key.in_(result_keys)
                    )
                )
            ).all()
        )
        detections_by_id = {detection.id: detection for detection in complete_evidence}
        events_by_id = {
            detection.source_event.id: detection.source_event for detection in complete_evidence
        }
        added_candidates = []
        for result in results:
            if result.correlation_key in existing_keys or new_detection_ids.isdisjoint(
                result.detection_ids
            ):
                continue
            candidate = CorrelationCandidate(
                correlation_key=result.correlation_key,
                device_id=result.device_id,
                strategy_id=result.strategy_id,
                start_timestamp=result.start_timestamp,
                end_timestamp=result.end_timestamp,
                confidence=result.confidence,
                aggregate_score=result.aggregate_score,
                reason=_PROCESS_LISTENER_REASON,
                detections=[detections_by_id[item_id] for item_id in result.detection_ids],
                events=[events_by_id[item_id] for item_id in result.event_ids],
            )
            session.add(candidate)
            existing_keys.add(result.correlation_key)
            added_candidates.append(candidate)
        return added_candidates

    @staticmethod
    def _evidence_for_anchor(
        anchor: Detection, evidence: Sequence[Detection]
    ) -> tuple[Detection, ...]:
        if anchor.rule_id != "LISTENER_OBSERVED":
            return tuple(evidence)
        return tuple(
            detection
            for detection in evidence
            if detection.rule_id != anchor.rule_id or detection.id == anchor.id
        )

    @staticmethod
    def _restore_utc_timezone(detections: Sequence[Detection]) -> None:
        """Restore UTC on timestamps returned without tzinfo by SQLite test databases."""
        for detection in detections:
            event = detection.source_event
            if event.timestamp.tzinfo is None:
                set_committed_value(event, "timestamp", event.timestamp.replace(tzinfo=UTC))
            if detection.timestamp.tzinfo is None:
                set_committed_value(detection, "timestamp", detection.timestamp.replace(tzinfo=UTC))
