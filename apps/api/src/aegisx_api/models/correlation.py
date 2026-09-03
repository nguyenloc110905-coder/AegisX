from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aegisx_api.db.base import Base

if TYPE_CHECKING:
    from aegisx_api.models.detection import Detection
    from aegisx_api.models.device import Device
    from aegisx_api.models.event import Event


correlation_candidate_detections = Table(
    "correlation_candidate_detections",
    Base.metadata,
    Column("candidate_id", Uuid(), primary_key=True),
    Column("detection_id", Uuid(), primary_key=True),
    ForeignKeyConstraint(
        ["candidate_id"],
        ["correlation_candidates.id"],
        name="fk_correlation_candidate_detections_candidate_id_correlation_candidates",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["detection_id"],
        ["detections.id"],
        name="fk_correlation_candidate_detections_detection_id_detections",
        ondelete="CASCADE",
    ),
)

correlation_candidate_events = Table(
    "correlation_candidate_events",
    Base.metadata,
    Column("candidate_id", Uuid(), primary_key=True),
    Column("event_id", Uuid(), primary_key=True),
    ForeignKeyConstraint(
        ["candidate_id"],
        ["correlation_candidates.id"],
        name="fk_correlation_candidate_events_candidate_id_correlation_candidates",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["event_id"],
        ["events.id"],
        name="fk_correlation_candidate_events_event_id_events",
        ondelete="CASCADE",
    ),
)


class CorrelationCandidate(Base):
    __tablename__ = "correlation_candidates"
    __table_args__ = (
        CheckConstraint("length(correlation_key) = 64", name="valid_correlation_key_length"),
        CheckConstraint("confidence IN ('low', 'medium', 'high')", name="valid_confidence"),
        CheckConstraint(
            "aggregate_score >= 0 AND aggregate_score <= 100", name="valid_aggregate_score"
        ),
        ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_correlation_candidates_device_id_devices",
            ondelete="CASCADE",
        ),
        UniqueConstraint("correlation_key", name="uq_correlation_candidates_correlation_key"),
        Index("ix_correlation_candidates_device_timestamp", "device_id", "start_timestamp"),
        Index("ix_correlation_candidates_strategy_timestamp", "strategy_id", "start_timestamp"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    correlation_key: Mapped[str] = mapped_column(String(64))
    device_id: Mapped[UUID] = mapped_column()
    strategy_id: Mapped[str] = mapped_column(String(128))
    start_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[str] = mapped_column(String(16))
    aggregate_score: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    device: Mapped["Device"] = relationship(back_populates="correlation_candidates")
    detections: Mapped[list["Detection"]] = relationship(
        secondary=correlation_candidate_detections,
        back_populates="correlation_candidates",
    )
    events: Mapped[list["Event"]] = relationship(
        secondary=correlation_candidate_events,
        back_populates="correlation_candidates",
    )
