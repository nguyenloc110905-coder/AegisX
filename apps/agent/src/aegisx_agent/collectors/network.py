import socket
from collections.abc import Callable, Iterable
from typing import Any

import psutil

from aegisx_agent.events import Observation


class NetworkCollector:
    source = "network_collector"

    def __init__(
        self,
        net_connections: Callable[..., Iterable[Any]] = psutil.net_connections,
        max_connections: int = 200,
    ) -> None:
        self._net_connections = net_connections
        self._max_connections = max_connections

    def collect(self) -> list[Observation]:
        try:
            connections = self._net_connections(kind="inet")
        except (psutil.AccessDenied, psutil.Error):
            return []

        observations: list[Observation] = []
        for connection in connections:
            if len(observations) >= self._max_connections:
                break
            local_ip, local_port = self._address(connection.laddr)
            if local_ip is None or local_port is None:
                continue
            remote_ip, remote_port = self._address(connection.raddr)
            protocol = "udp" if connection.type == socket.SOCK_DGRAM else "tcp"
            is_listener = connection.status == psutil.CONN_LISTEN or remote_ip is None
            data = {
                "pid": connection.pid,
                "local_ip": local_ip,
                "local_port": local_port,
                "protocol": protocol,
                "state": str(connection.status),
            }
            if not is_listener:
                data.update({"remote_ip": remote_ip, "remote_port": remote_port})
            observations.append(
                Observation(
                    event_type=(
                        "network.listener_observed"
                        if is_listener
                        else "network.connection_observed"
                    ),
                    source=self.source,
                    data=data,
                )
            )
        return observations

    @staticmethod
    def _address(address: Any) -> tuple[str | None, int | None]:
        if not address:
            return None, None
        try:
            return str(address.ip), int(address.port)
        except AttributeError:
            return str(address[0]), int(address[1])
