import os
import platform
import socket
import time

import psutil

from aegisx_agent.events import Observation


class SystemCollector:
    source = "system_collector"

    def collect(self) -> Observation:
        cpu_count = os.cpu_count() or 1
        return Observation(
            event_type="system.status",
            source=self.source,
            data={
                "hostname": socket.gethostname(),
                "os": platform.system(),
                "kernel": platform.release(),
                "uptime_seconds": max(0.0, time.time() - psutil.boot_time()),
                "cpu_count": cpu_count,
                "memory_total_bytes": psutil.virtual_memory().total,
            },
        )
