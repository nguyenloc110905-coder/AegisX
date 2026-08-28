from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aegisx_api.detection.engine import DetectionEngine
from aegisx_api.models.detection import Detection
from aegisx_api.models.device import Device
from aegisx_api.models.event import Event
from aegisx_api.schemas.event import EventBatchResponse, TelemetryEvent


class TelemetryIngestionService:
    def __init__(self, detection_engine: DetectionEngine) -> None:
        self._detection_engine = detection_engine

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

        for envelope in envelopes:
            if envelope.id in seen_ids:
                if envelope.id not in existing_ids:
                    duplicates += 1
                continue
            seen_ids.add(envelope.id)
            event = self._map_event(device.id, envelope)
            session.add(event)
            for result in self._detection_engine.evaluate(event):
                session.add(
                    Detection(
                        device_id=result.device_id,
                        source_event=event,
                        rule_id=result.rule_id,
                        timestamp=result.timestamp,
                        severity=result.severity,
                        score_contribution=result.score_contribution,
                        reason=result.reason,
                        evidence_event_ids=[
                            str(event_id) for event_id in result.evidence_event_ids
                        ],
                    )
                )
            accepted += 1

        device.last_seen_at = datetime.now(UTC)
        await session.commit()
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
