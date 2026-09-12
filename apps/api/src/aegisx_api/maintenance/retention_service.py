from datetime import datetime

from sqlalchemy import Select, and_, delete, exists, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from aegisx_api.maintenance.retention_policy import (
    RETENTION_POLICY_VERSION,
    RETENTION_RULES,
    cutoff_for,
)
from aegisx_api.maintenance.types import (
    DataStatus,
    EventTypeStats,
    PruneReport,
    PruneResult,
    PruneRuleReport,
)
from aegisx_api.models.correlation import (
    CorrelationCandidate,
    correlation_candidate_detections,
    correlation_candidate_events,
)
from aegisx_api.models.detection import Detection
from aegisx_api.models.event import Event
from aegisx_api.models.incident import (
    Incident,
    incident_detections,
    incident_events,
)


def _event_is_protected() -> ColumnElement[bool]:
    candidate_event = exists(
        select(1)
        .select_from(correlation_candidate_events)
        .where(correlation_candidate_events.c.event_id == Event.id)
    )
    incident_event = exists(
        select(1).select_from(incident_events).where(incident_events.c.event_id == Event.id)
    )
    candidate_detection = exists(
        select(1)
        .select_from(
            Detection.__table__.join(
                correlation_candidate_detections,
                correlation_candidate_detections.c.detection_id == Detection.id,
            )
        )
        .where(Detection.source_event_id == Event.id)
    )
    incident_detection = exists(
        select(1)
        .select_from(
            Detection.__table__.join(
                incident_detections,
                incident_detections.c.detection_id == Detection.id,
            )
        )
        .where(Detection.source_event_id == Event.id)
    )
    return or_(candidate_event, incident_event, candidate_detection, incident_detection)


async def _count(session: AsyncSession, statement: Select[tuple[int]]) -> int:
    return int(await session.scalar(statement) or 0)


class RetentionPruneError(RuntimeError):
    def __init__(
        self,
        *,
        deleted_events: int,
        deleted_detections: int,
        failure_category: str,
    ) -> None:
        super().__init__(f"retention prune failed: {failure_category}")
        self.deleted_events = deleted_events
        self.deleted_detections = deleted_detections
        self.failure_category = failure_category


class RetentionService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def data_status(self) -> DataStatus:
        async with self._session_factory() as session:
            event_rows = (
                await session.execute(
                    select(
                        Event.event_type,
                        func.count(Event.id),
                        func.min(Event.ingested_at),
                        func.max(Event.ingested_at),
                    )
                    .group_by(Event.event_type)
                    .order_by(func.count(Event.id).desc(), Event.event_type)
                )
            ).all()
            event_types = tuple(
                EventTypeStats(
                    event_type=str(row[0]),
                    count=int(row[1]),
                    oldest_ingested_at=row[2],
                    newest_ingested_at=row[3],
                )
                for row in event_rows
            )
            return DataStatus(
                policy_version=RETENTION_POLICY_VERSION,
                database_size_bytes=int(
                    await session.scalar(select(func.pg_database_size(func.current_database())))
                    or 0
                ),
                event_count=await _count(session, select(func.count()).select_from(Event)),
                detection_count=await _count(session, select(func.count()).select_from(Detection)),
                candidate_count=await _count(
                    session, select(func.count()).select_from(CorrelationCandidate)
                ),
                incident_count=await _count(session, select(func.count()).select_from(Incident)),
                protected_event_count=await _count(
                    session,
                    select(func.count()).select_from(Event).where(_event_is_protected()),
                ),
                event_types=event_types,
            )

    async def dry_run(self, evaluation_time: datetime) -> PruneReport:
        reports: list[PruneRuleReport] = []
        async with self._session_factory() as session:
            for rule in RETENTION_RULES:
                cutoff = cutoff_for(rule, evaluation_time)
                expired = and_(Event.event_type == rule.event_type, Event.ingested_at <= cutoff)
                protected = _event_is_protected()
                deletable = and_(expired, not_(protected))
                reports.append(
                    PruneRuleReport(
                        event_type=rule.event_type,
                        cutoff=cutoff,
                        expired_events=await _count(
                            session, select(func.count()).select_from(Event).where(expired)
                        ),
                        protected_events=await _count(
                            session,
                            select(func.count()).select_from(Event).where(expired, protected),
                        ),
                        deletable_events=await _count(
                            session, select(func.count()).select_from(Event).where(deletable)
                        ),
                        deletable_detections=await _count(
                            session,
                            select(func.count())
                            .select_from(Detection)
                            .join(Event, Event.id == Detection.source_event_id)
                            .where(deletable),
                        ),
                    )
                )
        return PruneReport(
            policy_version=RETENTION_POLICY_VERSION,
            evaluation_time=evaluation_time,
            rules=tuple(reports),
        )

    async def prune(self, evaluation_time: datetime, batch_size: int = 1000) -> PruneResult:
        if batch_size < 1 or batch_size > 1000:
            raise ValueError("batch_size must be between 1 and 1000")
        cutoff_for(RETENTION_RULES[0], evaluation_time)
        deleted_events = 0
        deleted_detections = 0
        try:
            for rule in RETENTION_RULES:
                cutoff = cutoff_for(rule, evaluation_time)
                while True:
                    batch_events, batch_detections = await self._prune_batch(
                        event_type=rule.event_type,
                        cutoff=cutoff,
                        batch_size=batch_size,
                    )
                    deleted_events += batch_events
                    deleted_detections += batch_detections
                    if batch_events == 0:
                        break
        except Exception as error:
            raise RetentionPruneError(
                deleted_events=deleted_events,
                deleted_detections=deleted_detections,
                failure_category=type(error).__name__,
            ) from error
        return PruneResult(
            policy_version=RETENTION_POLICY_VERSION,
            evaluation_time=evaluation_time,
            deleted_events=deleted_events,
            deleted_detections=deleted_detections,
            completed=True,
        )

    async def _prune_batch(
        self,
        *,
        event_type: str,
        cutoff: datetime,
        batch_size: int,
    ) -> tuple[int, int]:
        async with self._session_factory() as session:
            async with session.begin():
                selected_ids = tuple(
                    (
                        await session.scalars(
                            select(Event.id)
                            .where(
                                Event.event_type == event_type,
                                Event.ingested_at <= cutoff,
                                not_(_event_is_protected()),
                            )
                            .order_by(Event.ingested_at, Event.id)
                            .limit(batch_size)
                            .with_for_update(skip_locked=True)
                        )
                    ).all()
                )
                if not selected_ids:
                    return 0, 0
                deleted_detection_ids = tuple(
                    (
                        await session.scalars(
                            delete(Detection)
                            .where(Detection.source_event_id.in_(selected_ids))
                            .returning(Detection.id)
                        )
                    ).all()
                )
                deleted_event_ids = tuple(
                    (
                        await session.scalars(
                            delete(Event).where(Event.id.in_(selected_ids)).returning(Event.id)
                        )
                    ).all()
                )
            return len(deleted_event_ids), len(deleted_detection_ids)
