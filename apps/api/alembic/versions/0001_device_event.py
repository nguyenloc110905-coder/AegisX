"""Create device and event tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_device_event"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("os", sa.String(64), nullable=False),
        sa.Column("os_version", sa.String(128), nullable=False),
        sa.Column("kernel", sa.String(128), nullable=False),
        sa.Column("architecture", sa.String(64), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_devices"),
        sa.UniqueConstraint("external_id", name="uq_devices_external_id"),
        sa.UniqueConstraint("token_digest", name="uq_devices_token_digest"),
    )
    op.create_index("ix_devices_external_id", "devices", ["external_id"])
    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("severity_hint", sa.String(16), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("parent_process_id", sa.Integer(), nullable=True),
        sa.Column("executable", sa.String(4096), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("schema_version > 0", name="ck_events_positive_schema_version"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], name="fk_events_device_id_devices", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_events"),
    )
    op.create_index("ix_events_event_type", "events", ["event_type"])
    op.create_index("ix_events_device_timestamp", "events", ["device_id", "timestamp"])
    op.create_index("ix_events_device_process", "events", ["device_id", "process_id", "timestamp"])


def downgrade() -> None:
    op.drop_table("events")
    op.drop_table("devices")
