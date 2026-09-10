import hashlib
import struct
from datetime import timedelta

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from aegisx_api.incident.policies import registry
from aegisx_api.models.correlation import CorrelationCandidate
from aegisx_api.models.incident import Incident, IncidentStatusTransition

logger = structlog.get_logger(__name__)


class IncidentService:
    def __init__(
        self,
        evidence_window: timedelta = timedelta(seconds=3600),
        lock_timeout_ms: int = 2000,
    ) -> None:
        self._evidence_window = evidence_window
        self._lock_timeout_ms = lock_timeout_ms
        self._registry = registry

    def _hash_to_lock_id(self, grouping_key: str) -> int:
        digest = hashlib.sha256(grouping_key.encode("utf-8")).digest()
        value: int = struct.unpack(">q", digest[:8])[0]
        return value

    async def process_candidate(
        self, session: AsyncSession, candidate: CorrelationCandidate
    ) -> None:
        if candidate.confidence == "low" or candidate.aggregate_score < 30:
            return

        policies = self._registry.get_policies_for_strategy(candidate.strategy_id)
        if not policies:
            return
        if len(policies) > 1:
            logger.error(
                "incident_promotion_failed",
                candidate_id=str(candidate.id),
                failure_category="ambiguous_policy",
                evidence_committed=True,
            )
            return

        policy = policies[0]
        decision = policy.evaluate(candidate)
        if not decision:
            return

        if candidate.start_timestamp > candidate.end_timestamp:
            return

        if not candidate.events or not candidate.detections:
            return

        # Check if already attached
        existing_attachment_stmt = (
            select(Incident.id)
            .join(Incident.candidates)
            .where(CorrelationCandidate.id == candidate.id)
        )
        existing_attachment = (await session.scalars(existing_attachment_stmt)).first()
        if existing_attachment:
            return

        lock_id = self._hash_to_lock_id(decision.grouping_key)
        window = self._evidence_window

        try:
            # We assume this is called inside a nested transaction (savepoint)
            await session.execute(
                text(f"SET LOCAL statement_timeout = '{self._lock_timeout_ms}ms'")
            )
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id}
            )
            await session.execute(text("SET LOCAL statement_timeout = '0'"))
        except Exception:
            logger.error(
                "incident_promotion_failed",
                candidate_id=str(candidate.id),
                policy_id=decision.policy_id,
                grouping_key=decision.grouping_key,
                failure_category="lock_timeout",
                evidence_committed=True,
            )
            raise

        stmt = (
            select(Incident)
            .options(
                selectinload(Incident.candidates),
                selectinload(Incident.detections),
                selectinload(Incident.events),
            )
            .where(
                Incident.device_id == candidate.device_id,
                Incident.policy_id == decision.policy_id,
                Incident.policy_version == decision.policy_version,
                Incident.grouping_key == decision.grouping_key,
                Incident.status.in_(["OPEN", "INVESTIGATING"]),
                Incident.disposition == "UNDETERMINED",
            )
        )
        active_incidents = list((await session.scalars(stmt)).all())

        in_window_incidents = []
        for inc in active_incidents:
            if (
                candidate.start_timestamp <= inc.last_evidence_at + window
                and candidate.end_timestamp >= inc.first_evidence_at - window
            ):
                in_window_incidents.append(inc)

        if len(in_window_incidents) > 1:
            logger.error(
                "incident_promotion_failed",
                candidate_id=str(candidate.id),
                policy_id=decision.policy_id,
                failure_category="ambiguous_incidents",
                evidence_committed=True,
            )
            raise RuntimeError("Ambiguous incidents")

        if len(in_window_incidents) == 1:
            incident = in_window_incidents[0]
            outcome = "attached"

            incident.first_evidence_at = min(incident.first_evidence_at, candidate.start_timestamp)
            incident.last_evidence_at = max(incident.last_evidence_at, candidate.end_timestamp)
            incident.version += 1

            incident.candidates.append(candidate)

            existing_det_ids = {d.id for d in incident.detections}
            for d in candidate.detections:
                if d.id not in existing_det_ids:
                    incident.detections.append(d)
                    existing_det_ids.add(d.id)

            existing_ev_ids = {e.id for e in incident.events}
            for e in candidate.events:
                if e.id not in existing_ev_ids:
                    incident.events.append(e)
                    existing_ev_ids.add(e.id)

            incident.risk_score = min(100, sum(d.score_contribution for d in incident.detections))
            incident.severity = self._compute_severity(incident.risk_score)
            if candidate.confidence == "high":
                incident.confidence = "high"
        else:
            outcome = "created"
            seed_str = (
                f"{decision.policy_id}|{decision.policy_version}"
                f"|{candidate.device_id}|{decision.grouping_key}|{candidate.id}"
            )
            incident_key = hashlib.sha256(seed_str.encode("utf-8")).hexdigest()

            risk = min(100, sum(d.score_contribution for d in candidate.detections))
            sev = self._compute_severity(risk)

            incident = Incident(
                incident_key=incident_key,
                device_id=candidate.device_id,
                policy_id=decision.policy_id,
                policy_version=decision.policy_version,
                grouping_key=decision.grouping_key,
                title=decision.title,
                summary=decision.summary,
                status="OPEN",
                disposition="UNDETERMINED",
                severity=sev,
                risk_score=risk,
                confidence=candidate.confidence,
                promotion_score_threshold=decision.score_threshold,
                promotion_confidence_threshold=decision.confidence_threshold,
                evidence_window_seconds=int(window.total_seconds()),
                first_evidence_at=candidate.start_timestamp,
                last_evidence_at=candidate.end_timestamp,
                candidates=[candidate],
                detections=list(candidate.detections),
                events=list(candidate.events),
            )
            session.add(incident)

            transition = IncidentStatusTransition(
                incident=incident,
                from_status=None,
                from_disposition=None,
                to_status="OPEN",
                to_disposition="UNDETERMINED",
                actor_type="system",
                actor_id=None,
                reason=(
                    "Incident automatically created from correlation candidate promotion policy."
                ),
                incident_version=1,
            )
            session.add(transition)

        logger.info(
            "incident_promotion_success",
            candidate_id=str(candidate.id),
            policy_id=decision.policy_id,
            grouping_key=decision.grouping_key,
            outcome=outcome,
            incident_key=incident.incident_key,
            evidence_committed=True,
        )

    def _compute_severity(self, risk: int) -> str:
        if risk < 10:
            return "informational"
        if risk < 30:
            return "low"
        if risk < 60:
            return "medium"
        if risk < 80:
            return "high"
        return "critical"
