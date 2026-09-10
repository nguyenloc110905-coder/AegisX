from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql.elements import ColumnElement

from aegisx_api.console.types import (
    CandidateRow,
    DashboardCounts,
    DashboardSnapshot,
    DetectionRow,
    DeviceRow,
    EventRow,
    IncidentRow,
)
from aegisx_api.models.correlation import CorrelationCandidate
from aegisx_api.models.detection import Detection
from aegisx_api.models.device import Device
from aegisx_api.models.event import Event
from aegisx_api.models.incident import Incident


class ConsoleRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        engine: AsyncEngine | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._engine = engine

    @classmethod
    def from_url(cls, database_url: str) -> "ConsoleRepository":
        engine = create_async_engine(database_url, pool_pre_ping=True)
        return cls(async_sessionmaker(engine, expire_on_commit=False), engine=engine)

    async def load(self, limit: int = 200) -> DashboardSnapshot:
        bounded_limit = min(max(limit, 1), 500)
        async with self._session_factory() as session:
            counts = DashboardCounts(
                devices=await self._count(session, Device, Device.is_active.is_(True)),
                events=await self._count(session, Event),
                detections=await self._count(session, Detection),
                candidates=await self._count(session, CorrelationCandidate),
                open_incidents=await self._count(session, Incident, Incident.status == "OPEN"),
            )
            devices = tuple(
                DeviceRow(
                    id=row.id,
                    name=row.name,
                    os=row.os,
                    os_version=row.os_version,
                    kernel=row.kernel,
                    architecture=row.architecture,
                    is_active=row.is_active,
                    last_seen_at=row.last_seen_at,
                )
                for row in (
                    await session.scalars(
                        select(Device)
                        .order_by(Device.last_seen_at.desc().nullslast())
                        .limit(bounded_limit)
                    )
                ).all()
            )
            events = tuple(
                EventRow(
                    id=row.id,
                    timestamp=row.timestamp,
                    event_type=row.event_type,
                    process_id=row.process_id,
                    executable=row.executable,
                    local_ip=row.local_ip,
                    local_port=row.local_port,
                    remote_ip=row.remote_ip,
                    remote_port=row.remote_port,
                    severity=row.severity_hint,
                )
                for row in (
                    await session.scalars(
                        select(Event).order_by(Event.timestamp.desc()).limit(bounded_limit)
                    )
                ).all()
            )
            detections = tuple(
                DetectionRow(
                    id=row.id,
                    timestamp=row.timestamp,
                    rule_id=row.rule_id,
                    severity=row.severity,
                    score=row.score_contribution,
                    reason=row.reason,
                )
                for row in (
                    await session.scalars(
                        select(Detection).order_by(Detection.timestamp.desc()).limit(bounded_limit)
                    )
                ).all()
            )
            candidates = tuple(
                CandidateRow(
                    id=row.id,
                    timestamp=row.start_timestamp,
                    strategy_id=row.strategy_id,
                    confidence=row.confidence,
                    score=row.aggregate_score,
                    reason=row.reason,
                )
                for row in (
                    await session.scalars(
                        select(CorrelationCandidate)
                        .order_by(CorrelationCandidate.start_timestamp.desc())
                        .limit(bounded_limit)
                    )
                ).all()
            )
            incidents = tuple(
                IncidentRow(
                    id=row.id,
                    timestamp=row.last_evidence_at,
                    title=row.title,
                    severity=row.severity,
                    risk_score=row.risk_score,
                    status=row.status,
                    confidence=row.confidence,
                    disposition=row.disposition,
                )
                for row in (
                    await session.scalars(
                        select(Incident)
                        .order_by(Incident.last_evidence_at.desc())
                        .limit(bounded_limit)
                    )
                ).all()
            )
        return DashboardSnapshot(counts, devices, events, detections, candidates, incidents)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()

    @staticmethod
    async def _count(
        session: AsyncSession,
        model: type[Device]
        | type[Event]
        | type[Detection]
        | type[CorrelationCandidate]
        | type[Incident],
        criterion: ColumnElement[bool] | None = None,
    ) -> int:
        statement = select(func.count()).select_from(model)
        if criterion is not None:
            statement = statement.where(criterion)
        return int((await session.scalar(statement)) or 0)
