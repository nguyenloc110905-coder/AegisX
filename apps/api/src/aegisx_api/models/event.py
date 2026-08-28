from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aegisx_api.db.base import Base


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("schema_version > 0", name="positive_schema_version"),
        Index("ix_events_device_timestamp", "device_id", "timestamp"),
        Index("ix_events_device_process", "device_id", "process_id", "timestamp"),
        Index("ix_events_device_remote", "device_id", "remote_ip", "remote_port", "timestamp"),
        Index("ix_events_device_local", "device_id", "local_ip", "local_port", "timestamp"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    schema_version: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64))
    severity_hint: Mapped[str] = mapped_column(String(16))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)
    process_id: Mapped[int | None] = mapped_column(Integer)
    parent_process_id: Mapped[int | None] = mapped_column(Integer)
    executable: Mapped[str | None] = mapped_column(String(4096))
    local_ip: Mapped[str | None] = mapped_column(String(45))
    local_port: Mapped[int | None] = mapped_column(Integer)
    remote_ip: Mapped[str | None] = mapped_column(String(45))
    remote_port: Mapped[int | None] = mapped_column(Integer)
    protocol: Mapped[str | None] = mapped_column(String(8))
    connection_state: Mapped[str | None] = mapped_column(String(32))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    device: Mapped["Device"] = relationship(back_populates="events")
    detections: Mapped[list["Detection"]] = relationship(
        back_populates="source_event", cascade="all, delete"
    )


from aegisx_api.models.detection import Detection  # noqa: E402
from aegisx_api.models.device import Device  # noqa: E402
