"""Add the Event retention scan index."""

from alembic import op

revision = "0006_event_retention_index"
down_revision = "0005_incident_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_events_event_type_ingested_at",
        "events",
        ["event_type", "ingested_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_events_event_type_ingested_at", table_name="events")
