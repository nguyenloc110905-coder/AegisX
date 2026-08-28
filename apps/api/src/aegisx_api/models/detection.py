from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aegisx_api.db.base import Base


class Detection(Base):
    __tablename__ = "detections"
    __table_args__ = (
        CheckConstraint(
            "score_contribution >= 0 AND score_contribution <= 100",
            name="valid_score_contribution",
        ),
        Index("ix_detections_device_timestamp", "device_id", "timestamp"),
        Index("ix_detections_rule_timestamp", "rule_id", "timestamp"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    source_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str] = mapped_column(String(128))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    severity: Mapped[str] = mapped_column(String(16))
    score_contribution: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(2048))
    evidence_event_ids: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    device: Mapped["Device"] = relationship(back_populates="detections")
    source_event: Mapped["Event"] = relationship(back_populates="detections")


from aegisx_api.models.device import Device  # noqa: E402
from aegisx_api.models.event import Event  # noqa: E402
