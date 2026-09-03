"""Add promoted network event fields."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_network_fields"
down_revision: str | None = "0001_device_event"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("local_ip", sa.String(45), nullable=True))
    op.add_column("events", sa.Column("local_port", sa.Integer(), nullable=True))
    op.add_column("events", sa.Column("remote_ip", sa.String(45), nullable=True))
    op.add_column("events", sa.Column("remote_port", sa.Integer(), nullable=True))
    op.add_column("events", sa.Column("protocol", sa.String(8), nullable=True))
    op.add_column("events", sa.Column("connection_state", sa.String(32), nullable=True))
    op.create_index(
        "ix_events_device_remote",
        "events",
        ["device_id", "remote_ip", "remote_port", "timestamp"],
    )
    op.create_index(
        "ix_events_device_local",
        "events",
        ["device_id", "local_ip", "local_port", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_events_device_local", table_name="events")
    op.drop_index("ix_events_device_remote", table_name="events")
    op.drop_column("events", "connection_state")
    op.drop_column("events", "protocol")
    op.drop_column("events", "remote_port")
    op.drop_column("events", "remote_ip")
    op.drop_column("events", "local_port")
    op.drop_column("events", "local_ip")
