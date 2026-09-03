"""Create correlation candidate storage."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_correlation_foundation"
down_revision: str | None = "0003_detection_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "correlation_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("correlation_key", sa.String(64), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("strategy_id", sa.String(128), nullable=False),
        sa.Column("start_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("aggregate_score", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(2048), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(correlation_key) = 64",
            name="ck_correlation_candidates_valid_correlation_key_length",
        ),
        sa.CheckConstraint(
            "confidence IN ('low', 'medium', 'high')",
            name="ck_correlation_candidates_valid_confidence",
        ),
        sa.CheckConstraint(
            "aggregate_score >= 0 AND aggregate_score <= 100",
            name="ck_correlation_candidates_valid_aggregate_score",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_correlation_candidates_device_id_devices",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_correlation_candidates"),
        sa.UniqueConstraint("correlation_key", name="uq_correlation_candidates_correlation_key"),
    )
    op.create_index(
        "ix_correlation_candidates_device_timestamp",
        "correlation_candidates",
        ["device_id", "start_timestamp"],
    )
    op.create_index(
        "ix_correlation_candidates_strategy_timestamp",
        "correlation_candidates",
        ["strategy_id", "start_timestamp"],
    )
    op.create_table(
        "correlation_candidate_detections",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("detection_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["correlation_candidates.id"],
            name="fk_correlation_candidate_detections_candidate_id_correlation_candidates",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["detection_id"],
            ["detections.id"],
            name="fk_correlation_candidate_detections_detection_id_detections",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "candidate_id", "detection_id", name="pk_correlation_candidate_detections"
        ),
    )
    op.create_table(
        "correlation_candidate_events",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["correlation_candidates.id"],
            name="fk_correlation_candidate_events_candidate_id_correlation_candidates",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name="fk_correlation_candidate_events_event_id_events",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("candidate_id", "event_id", name="pk_correlation_candidate_events"),
    )


def downgrade() -> None:
    op.drop_table("correlation_candidate_events")
    op.drop_table("correlation_candidate_detections")
    op.drop_index(
        "ix_correlation_candidates_strategy_timestamp", table_name="correlation_candidates"
    )
    op.drop_index("ix_correlation_candidates_device_timestamp", table_name="correlation_candidates")
    op.drop_table("correlation_candidates")
