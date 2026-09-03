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
    from aegisx_api.models.correlation import CorrelationCandidate
    from aegisx_api.models.detection import Detection
    from aegisx_api.models.device import Device
    from aegisx_api.models.event import Event


incident_correlation_candidates = Table(
    "incident_correlation_candidates",
    Base.metadata,
    Column("incident_id", Uuid(), primary_key=True),
    Column("candidate_id", Uuid(), primary_key=True),
    ForeignKeyConstraint(
        ["incident_id"],
        ["incidents.id"],
        name="fk_incident_candidates_incident",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["candidate_id"],
        ["correlation_candidates.id"],
        name="fk_incident_candidates_candidate",
        ondelete="CASCADE",
    ),
    UniqueConstraint("candidate_id", name="uq_incident_correlation_candidates_candidate_id"),
)

incident_detections = Table(
    "incident_detections",
    Base.metadata,
    Column("incident_id", Uuid(), primary_key=True),
    Column("detection_id", Uuid(), primary_key=True),
    ForeignKeyConstraint(
        ["incident_id"],
        ["incidents.id"],
        name="fk_incident_detections_incident",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["detection_id"],
        ["detections.id"],
        name="fk_incident_detections_detection",
        ondelete="CASCADE",
    ),
)

incident_events = Table(
    "incident_events",
    Base.metadata,
    Column("incident_id", Uuid(), primary_key=True),
    Column("event_id", Uuid(), primary_key=True),
    ForeignKeyConstraint(
        ["incident_id"],
        ["incidents.id"],
        name="fk_incident_events_incident",
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["event_id"],
        ["events.id"],
        name="fk_incident_events_event",
        ondelete="CASCADE",
    ),
)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint("length(incident_key) = 64", name="valid_incident_key_length"),
        CheckConstraint("policy_version > 0", name="valid_policy_version"),
        CheckConstraint("length(grouping_key) = 64", name="valid_grouping_key_length"),
        CheckConstraint("status IN ('OPEN', 'INVESTIGATING', 'RESOLVED')", name="valid_status"),
        CheckConstraint(
            "disposition IN ('UNDETERMINED', 'BENIGN', 'FALSE_POSITIVE', 'CONFIRMED_THREAT')",
            name="valid_disposition",
        ),
        CheckConstraint(
            "severity IN ('informational', 'low', 'medium', 'high', 'critical')",
            name="valid_severity",
        ),
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="valid_risk_score"),
        CheckConstraint("confidence IN ('medium', 'high')", name="valid_confidence"),
        CheckConstraint(
            "promotion_score_threshold >= 0 AND promotion_score_threshold <= 100",
            name="valid_promotion_score_threshold",
        ),
        CheckConstraint(
            "evidence_window_seconds >= 1 AND evidence_window_seconds <= 86400",
            name="valid_evidence_window_seconds",
        ),
        CheckConstraint("last_evidence_at >= first_evidence_at", name="valid_evidence_bounds"),
        CheckConstraint("version > 0", name="valid_version"),
        CheckConstraint(
            "(status = 'RESOLVED' AND closed_at IS NOT NULL)"
            " OR (status != 'RESOLVED' AND closed_at IS NULL)",
            name="valid_closed_at",
        ),
        CheckConstraint(
            "(status = 'RESOLVED' AND disposition != 'UNDETERMINED') OR (status != 'RESOLVED')",
            name="valid_resolved_disposition",
        ),
        ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_incidents_device_id_devices",
            ondelete="CASCADE",
        ),
        UniqueConstraint("incident_key", name="uq_incidents_incident_key"),
        Index(
            "ix_incidents_device_status_last_evidence",
            "device_id",
            "status",
            "last_evidence_at",
        ),
        Index(
            "ix_incidents_policy_status_last_evidence",
            "policy_id",
            "status",
            "last_evidence_at",
        ),
        Index(
            "ix_incidents_grouping_last_evidence",
            "device_id",
            "policy_id",
            "policy_version",
            "grouping_key",
            "last_evidence_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    incident_key: Mapped[str] = mapped_column(String(64))
    device_id: Mapped[UUID] = mapped_column()
    policy_id: Mapped[str] = mapped_column(String(128))
    policy_version: Mapped[int] = mapped_column(Integer)
    grouping_key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256))
    summary: Mapped[str] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(32))
    disposition: Mapped[str] = mapped_column(String(32), server_default="UNDETERMINED")
    severity: Mapped[str] = mapped_column(String(16))
    risk_score: Mapped[int] = mapped_column(Integer)
    risk_calculation_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    confidence: Mapped[str] = mapped_column(String(16))
    promotion_score_threshold: Mapped[int] = mapped_column(Integer)
    promotion_confidence_threshold: Mapped[str] = mapped_column(String(16))
    evidence_window_seconds: Mapped[int] = mapped_column(Integer)
    first_evidence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_evidence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    device: Mapped["Device"] = relationship(back_populates="incidents")
    candidates: Mapped[list["CorrelationCandidate"]] = relationship(
        secondary=incident_correlation_candidates,
    )
    detections: Mapped[list["Detection"]] = relationship(
        secondary=incident_detections,
    )
    events: Mapped[list["Event"]] = relationship(
        secondary=incident_events,
    )
    status_transitions: Mapped[list["IncidentStatusTransition"]] = relationship(
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="IncidentStatusTransition.occurred_at",
    )

    __mapper_args__ = {"version_id_col": version}


class IncidentStatusTransition(Base):
    __tablename__ = "incident_status_transitions"
    __table_args__ = (
        CheckConstraint("actor_type IN ('system', 'operator')", name="valid_actor_type"),
        CheckConstraint(
            "(actor_type = 'system' AND actor_id IS NULL)"
            " OR (actor_type = 'operator' AND actor_id IS NOT NULL)",
            name="valid_actor_id",
        ),
        CheckConstraint("incident_version > 0", name="valid_incident_version"),
        ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name="fk_incident_status_transitions_incident_id_incidents",
            ondelete="CASCADE",
        ),
        Index("ix_incident_status_transitions_timeline", "incident_id", "occurred_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    incident_id: Mapped[UUID] = mapped_column()
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    from_disposition: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32))
    to_disposition: Mapped[str] = mapped_column(String(32))
    actor_type: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reason: Mapped[str] = mapped_column(String(2048))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    incident_version: Mapped[int] = mapped_column(Integer)

    incident: Mapped["Incident"] = relationship(back_populates="status_transitions")
