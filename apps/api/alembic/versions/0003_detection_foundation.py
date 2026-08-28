"""Create detection foundation storage."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_detection_foundation"
down_revision: str | None = "0002_network_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "detections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.String(128), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("score_contribution", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(2048), nullable=False),
        sa.Column("evidence_event_ids", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "score_contribution >= 0 AND score_contribution <= 100",
            name="ck_detections_valid_score_contribution",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_detections_device_id_devices",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id"],
            ["events.id"],
            name="fk_detections_source_event_id_events",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_detections"),
    )
    op.create_index("ix_detections_device_id", "detections", ["device_id"])
    op.create_index("ix_detections_source_event_id", "detections", ["source_event_id"])
    op.create_index(
        "ix_detections_device_timestamp", "detections", ["device_id", "timestamp"]
    )
    op.create_index(
        "ix_detections_rule_timestamp", "detections", ["rule_id", "timestamp"]
    )


def downgrade() -> None:
    op.drop_table("detections")
