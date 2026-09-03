from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aegisx_api.detection.engine import DetectionEngine
from aegisx_api.models.correlation import CorrelationCandidate
from aegisx_api.models.detection import Detection
from aegisx_api.models.device import Device
from aegisx_api.models.event import Event
from aegisx_api.schemas.event import EventBatchResponse, TelemetryEvent
from aegisx_api.services.correlation import CorrelationService
from aegisx_api.services.incident import IncidentService

logger = structlog.get_logger(__name__)


class TelemetryIngestionService:
    def __init__(
        self,
        detection_engine: DetectionEngine,
        correlation_service: CorrelationService,
        incident_service: IncidentService,
        correlation_window: timedelta,
    ) -> None:
        self._detection_engine = detection_engine
        self._correlation_service = correlation_service
        self._incident_service = incident_service
        self._correlation_window = correlation_window

    async def ingest(
        self,
        session: AsyncSession,
        device: Device,
        envelopes: Sequence[TelemetryEvent],
    ) -> EventBatchResponse:
        event_ids = [envelope.id for envelope in envelopes]
        existing_ids = set(
            (await session.scalars(select(Event.id).where(Event.id.in_(event_ids)))).all()
        )
        seen_ids = set(existing_ids)
        accepted = 0
        duplicates = len(existing_ids)
        new_detections: list[Detection] = []
        correlation_outcome: str | None = None
        correlation_strategy_ids: tuple[str, ...] = ()
        correlation_candidate_count = 0
        correlation_failure_category: str | None = None

        for envelope in envelopes:
            if envelope.id in seen_ids:
                if envelope.id not in existing_ids:
                    duplicates += 1
                continue
            seen_ids.add(envelope.id)
            event = self._map_event(device.id, envelope)
            session.add(event)
            for result in self._detection_engine.evaluate(event):
                detection = Detection(
                    device_id=result.device_id,
                    source_event=event,
                    rule_id=result.rule_id,
                    timestamp=result.timestamp,
                    severity=result.severity,
                    score_contribution=result.score_contribution,
                    reason=result.reason,
                    evidence_event_ids=[str(event_id) for event_id in result.evidence_event_ids],
                )
                session.add(detection)
                new_detections.append(detection)
            accepted += 1

        device.last_seen_at = datetime.now(UTC)
        await session.flush()
        if new_detections:
            new_candidates: Sequence[CorrelationCandidate] = ()
            try:
                correlation_strategy_ids = self._correlation_service.strategy_ids_for(
                    new_detections
                )
                async with session.begin_nested():
                    new_candidates = await self._correlation_service.correlate(
                        session,
                        device.id,
                        new_detections,
                        self._correlation_window,
                    )
                correlation_candidate_count = len(new_candidates)
                correlation_outcome = (
                    "candidate_created" if correlation_candidate_count else "no_candidate"
                )
            except Exception as error:
                correlation_outcome = "failed"
                correlation_failure_category = type(error).__name__

            if new_candidates:
                for candidate in new_candidates:
                    try:
                        async with session.begin_nested():
                            await self._incident_service.process_candidate(session, candidate)
                    except Exception:
                        logger.debug(
                            "incident_promotion_skipped",
                            candidate_id=str(candidate.id),
                            reason="exception_logged_in_incident_service",
                        )
        await session.commit()
        if correlation_outcome is not None:
            log_context = {
                "strategy_ids": list(correlation_strategy_ids),
                "device_id": str(device.id),
                "outcome": correlation_outcome,
                "evidence_committed": True,
            }
            if correlation_failure_category is not None:
                logger.error(
                    "correlation_outcome",
                    **log_context,
                    failure_category=correlation_failure_category,
                )
            else:
                logger.info(
                    "correlation_outcome",
                    **log_context,
                    candidate_count=correlation_candidate_count,
                )
        return EventBatchResponse(accepted=accepted, duplicates=duplicates)

    @staticmethod
    def _map_event(device_id: UUID, envelope: TelemetryEvent) -> Event:
        data = envelope.data.model_dump(mode="json")
        return Event(
            id=envelope.id,
            device_id=device_id,
            schema_version=envelope.schema_version,
            timestamp=envelope.timestamp,
            event_type=envelope.event_type,
            source=envelope.source,
            severity_hint=envelope.severity_hint,
            data=data,
            metadata_=envelope.metadata,
            process_id=data.get("pid"),
            parent_process_id=data.get("ppid"),
            executable=data.get("executable"),
            local_ip=data.get("local_ip"),
            local_port=data.get("local_port"),
            remote_ip=data.get("remote_ip"),
            remote_port=data.get("remote_port"),
            protocol=data.get("protocol"),
            connection_state=data.get("state"),
        )
