from aegisx_api.detection.types import DetectionSeverity, RuleMatch
from aegisx_api.models.event import Event


class ListenerOpenedRule:
    rule_id = "LISTENER_OPENED"
    name = "Listener opened"
    description = "Records a listener endpoint that appeared between complete snapshots."
    category = "network"
    severity: DetectionSeverity = "low"
    score_contribution = 5
    event_types = frozenset({"network.listener_opened"})

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
            reason=(
                f"{protocol.upper()} listener appeared at {local_ip}:{local_port}{pid_suffix} "
                "between complete snapshots."
            ),
            evidence_event_ids=(event.id,),
        )
