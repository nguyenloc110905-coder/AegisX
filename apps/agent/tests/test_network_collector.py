import socket
from types import SimpleNamespace

import psutil

from aegisx_agent.collectors.network import NetworkCollector


def connection(*, status: str, laddr, raddr=(), pid: int | None = 42, kind=socket.SOCK_STREAM):
    return SimpleNamespace(status=status, laddr=laddr, raddr=raddr, pid=pid, type=kind)


def test_network_collector_emits_listener_and_connection() -> None:
    entries = [
        connection(status=psutil.CONN_LISTEN, laddr=("127.0.0.1", 8080)),
        connection(
            status=psutil.CONN_ESTABLISHED,
            laddr=("192.0.2.10", 50000),
            raddr=("198.51.100.20", 443),
        ),
    ]

    events = NetworkCollector(net_connections=lambda kind: entries).collect()

    assert [event.event_type for event in events] == [
        "network.listener",
        "network.connection",
    ]
    assert events[0].data["local_port"] == 8080
    assert events[0].data["pid"] == 42
    assert events[1].data["remote_ip"] == "198.51.100.20"
    assert events[1].data["remote_port"] == 443
    assert events[1].data["protocol"] == "tcp"


def test_network_collector_handles_udp_missing_pid_and_bounds() -> None:
    entries = [
        connection(status="NONE", laddr=("127.0.0.1", port), pid=None, kind=socket.SOCK_DGRAM)
        for port in range(5000, 5003)
    ]

    events = NetworkCollector(net_connections=lambda kind: entries, max_connections=2).collect()

    assert len(events) == 2
    assert all(event.event_type == "network.listener" for event in events)
    assert all(event.data["pid"] is None for event in events)
    assert all(event.data["protocol"] == "udp" for event in events)


def test_network_collector_degrades_when_access_is_denied() -> None:
    def denied(kind: str):
        raise psutil.AccessDenied(pid=1)

    assert NetworkCollector(net_connections=denied).collect() == []
