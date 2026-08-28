from aegisx_api.detection.types import DetectionSeverity, RuleMatch
from aegisx_api.models.event import Event


class ProcessStartedRule:
    rule_id = "PROCESS_STARTED"
    name = "Process started"
    description = "Recognizes a process identity newly observed after the agent baseline."
    category = "process"
    severity: DetectionSeverity = "informational"
    score_contribution = 0
    event_types = frozenset({"process.started"})

    def evaluate(self, event: Event) -> RuleMatch | None:
        if event.event_type not in self.event_types:
            return None
        pid = event.data.get("pid")
        name = event.data.get("name")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return None
        if not isinstance(name, str) or not name:
            return None
        return RuleMatch(
            reason=f"Process {name} (PID {pid}) was newly observed after the process baseline.",
            evidence_event_ids=(event.id,),
        )
