import socket
from pathlib import Path
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
        "network.listener_observed",
        "network.connection_observed",
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
    assert all(event.event_type == "network.listener_observed" for event in events)
    assert all(event.data["pid"] is None for event in events)
    assert all(event.data["protocol"] == "udp" for event in events)


def test_network_collector_degrades_when_access_is_denied() -> None:
    def denied(kind: str):
        raise psutil.AccessDenied(pid=1)

    assert NetworkCollector(net_connections=denied).collect() == []


def test_network_collector_repeated_snapshot_is_observed_but_not_reopened(tmp_path: Path) -> None:
    entries = [connection(status=psutil.CONN_LISTEN, laddr=("127.0.0.1", 8080))]
    collector = NetworkCollector(
        net_connections=lambda kind: entries,
        state_path=tmp_path / "network-state.json",
    )

    baseline = collector.collect()
    repeated = collector.collect()

    assert [event.event_type for event in baseline] == ["network.listener_observed"]
    assert [event.event_type for event in repeated] == ["network.listener_observed"]


def test_network_collector_proves_listener_opened_and_closed(tmp_path: Path) -> None:
    entries = [connection(status=psutil.CONN_LISTEN, laddr=("127.0.0.1", 8080))]
    collector = NetworkCollector(
        net_connections=lambda kind: entries,
        state_path=tmp_path / "network-state.json",
    )
    collector.collect()

    entries.append(connection(status=psutil.CONN_LISTEN, laddr=("127.0.0.1", 9000), pid=99))
    opened = collector.collect()
    entries.pop()
    closed = collector.collect()

    assert [event.event_type for event in opened] == [
        "network.listener_observed",
        "network.listener_observed",
        "network.listener_opened",
    ]
    assert opened[-1].data["local_port"] == 9000
    assert opened[-1].data["pid"] == 99
    assert [event.event_type for event in closed] == [
        "network.listener_observed",
        "network.listener_closed",
    ]
    assert closed[-1].data["local_port"] == 9000


def test_network_collector_proves_connection_opened_and_closed(tmp_path: Path) -> None:
    entries: list = []
    collector = NetworkCollector(
        net_connections=lambda kind: entries,
        state_path=tmp_path / "network-state.json",
    )
    collector.collect()
    entries.append(
        connection(
            status=psutil.CONN_ESTABLISHED,
            laddr=("192.0.2.10", 50000),
            raddr=("198.51.100.20", 443),
        )
    )

    opened = collector.collect()
    entries.clear()
    closed = collector.collect()

    assert [event.event_type for event in opened] == [
        "network.connection_observed",
        "network.connection_opened",
    ]
    assert [event.event_type for event in closed] == ["network.connection_closed"]
    assert closed[0].data["remote_ip"] == "198.51.100.20"


def test_network_collector_restart_reads_persisted_baseline(tmp_path: Path) -> None:
    state_path = tmp_path / "network-state.json"
    entry = connection(status=psutil.CONN_LISTEN, laddr=("127.0.0.1", 8080))
    NetworkCollector(net_connections=lambda kind: [entry], state_path=state_path).collect()

    repeated = NetworkCollector(
        net_connections=lambda kind: [entry], state_path=state_path
    ).collect()

    assert [event.event_type for event in repeated] == ["network.listener_observed"]


def test_network_collector_does_not_attribute_ambiguous_duplicate_open(tmp_path: Path) -> None:
    entries: list = []
    collector = NetworkCollector(
        net_connections=lambda kind: entries,
        state_path=tmp_path / "network-state.json",
    )
    collector.collect()
    entries.extend(
        [
            connection(status=psutil.CONN_LISTEN, laddr=("127.0.0.1", 8080), pid=42),
            connection(status=psutil.CONN_LISTEN, laddr=("127.0.0.1", 8080), pid=43),
        ]
    )

    ambiguous = collector.collect()
    entries[:] = [entries[0]]
    unique_later = collector.collect()

    assert [event.event_type for event in ambiguous] == [
        "network.listener_observed",
        "network.listener_observed",
    ]
    assert [event.event_type for event in unique_later] == ["network.listener_observed"]


def test_network_collector_incomplete_snapshot_cannot_close_prior_socket(tmp_path: Path) -> None:
    entries = [connection(status=psutil.CONN_LISTEN, laddr=("127.0.0.1", 8080))]
    collector = NetworkCollector(
        net_connections=lambda kind: entries,
        state_path=tmp_path / "network-state.json",
    )
    collector.collect()

    entries[:] = [connection(status=psutil.CONN_LISTEN, laddr=object())]
    incomplete = collector.collect()
    entries[:] = [connection(status=psutil.CONN_LISTEN, laddr=("127.0.0.1", 8080))]
    recovered = collector.collect()

    assert incomplete == []
    assert [event.event_type for event in recovered] == ["network.listener_observed"]


def test_network_collector_failed_snapshot_retains_prior_baseline(tmp_path: Path) -> None:
    calls: list[object] = [
        [connection(status=psutil.CONN_LISTEN, laddr=("127.0.0.1", 8080))],
        psutil.AccessDenied(pid=1),
        [connection(status=psutil.CONN_LISTEN, laddr=("127.0.0.1", 8080))],
    ]

    def changing_snapshot(kind: str):
        result = calls.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    collector = NetworkCollector(
        net_connections=changing_snapshot,
        state_path=tmp_path / "network-state.json",
    )

    collector.collect()
    assert collector.collect() == []
    assert [event.event_type for event in collector.collect()] == ["network.listener_observed"]


def test_network_collector_bounds_transition_output_without_truncating_state(
    tmp_path: Path,
) -> None:
    entries = [
        connection(status=psutil.CONN_LISTEN, laddr=("127.0.0.1", port))
        for port in (8001, 8002, 8003)
    ]
    collector = NetworkCollector(
        net_connections=lambda kind: entries,
        max_connections=1,
        state_path=tmp_path / "network-state.json",
    )
    collector.collect()
    entries.clear()

    closed = collector.collect()

    assert len(closed) == 1
    assert closed[0].event_type == "network.listener_closed"
