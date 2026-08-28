from aegisx_api.detection.types import DetectionSeverity, RuleMatch
from aegisx_api.models.event import Event


class ListenerObservedRule:
    rule_id = "LISTENER_OBSERVED"
    name = "Listener observed"
    description = "Records snapshot evidence of a listening socket without claiming a transition."
    category = "network"
    severity: DetectionSeverity = "low"
    score_contribution = 5
    event_types = frozenset({"network.listener_observed"})

    def evaluate(self, event: Event) -> RuleMatch | None:
        if event.event_type not in self.event_types:
            return None
        protocol = event.data.get("protocol")
        local_ip = event.data.get("local_ip")
        local_port = event.data.get("local_port")
        pid = event.data.get("pid")
        if protocol not in {"tcp", "udp"} or not isinstance(local_ip, str):
            return None
        if isinstance(local_port, bool) or not isinstance(local_port, int):
            return None
        if not 0 <= local_port <= 65535:
            return None
        if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0):
            return None
        pid_suffix = "" if pid is None else f" (PID {pid})"
        return RuleMatch(
            reason=f"{protocol.upper()} listener observed at {local_ip}:{local_port}{pid_suffix}.",
            evidence_event_ids=(event.id,),
        )
