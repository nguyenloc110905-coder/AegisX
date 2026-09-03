import ipaddress
import json
import os
import socket
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import psutil

from aegisx_agent.events import Observation

type SocketKind = Literal["listener", "connection"]


@dataclass(frozen=True)
class SocketRecord:
    kind: SocketKind
    key: str
    data: dict[str, Any]
    ambiguous: bool = False


class NetworkCollector:
    source = "network_collector"

    def __init__(
        self,
        net_connections: Callable[..., Iterable[Any]] = psutil.net_connections,
        max_connections: int = 200,
        state_path: Path | None = None,
    ) -> None:
        self._net_connections = net_connections
        self._max_connections = max_connections
        self._state_path = state_path
        self._memory_state: dict[str, SocketRecord] | None = None

    def collect(self) -> list[Observation]:
        previous = self._load_state()
        records: list[SocketRecord] = []
        snapshot_complete = True
        try:
            connections = self._net_connections(kind="inet")
            for connection in connections:
                try:
                    records.append(self._record(connection))
                except (AttributeError, IndexError, TypeError, ValueError):
                    snapshot_complete = False
        except (psutil.AccessDenied, psutil.Error):
            return []

        observations = [self._observed(record) for record in records[: self._max_connections]]
        if not snapshot_complete:
            return observations

        current = self._collapse_records(records)
        if previous is not None:
            transition_budget = self._max_connections
            for key in sorted(current.keys() - previous.keys()):
                record = current[key]
                if transition_budget and not record.ambiguous:
                    observations.append(self._transition(record, "opened"))
                    transition_budget -= 1
            for key in sorted(previous.keys() - current.keys()):
                if not transition_budget:
                    break
                observations.append(self._transition(previous[key], "closed"))
                transition_budget -= 1
        self._save_state(current)
        return observations

    def _record(self, connection: Any) -> SocketRecord:
        local_ip, local_port = self._address(connection.laddr)
        protocol = "udp" if connection.type == socket.SOCK_DGRAM else "tcp"
        state = str(connection.status)
        pid = connection.pid
        if pid is not None:
            pid = int(pid)
            if pid <= 0:
                raise ValueError("socket PID must be positive when present")
        data: dict[str, Any] = {
            "pid": pid,
            "local_ip": local_ip,
            "local_port": local_port,
            "protocol": protocol,
            "state": state,
        }
        is_listener = connection.status == psutil.CONN_LISTEN or not connection.raddr
        identity: tuple[str | int, ...]
        if is_listener:
            identity = ("listener", protocol, local_ip, local_port)
            kind: SocketKind = "listener"
        else:
            remote_ip, remote_port = self._address(connection.raddr)
            data.update({"remote_ip": remote_ip, "remote_port": remote_port})
            identity = (
                "connection",
                protocol,
                local_ip,
                local_port,
                remote_ip,
                remote_port,
            )
            kind = "connection"
        return SocketRecord(kind=kind, key=json.dumps(identity, separators=(",", ":")), data=data)

    @staticmethod
    def _collapse_records(records: list[SocketRecord]) -> dict[str, SocketRecord]:
        counts = Counter(record.key for record in records)
        collapsed: dict[str, SocketRecord] = {}
        for record in records:
            if record.key in collapsed:
                continue
            if counts[record.key] == 1:
                collapsed[record.key] = record
                continue
            duplicate_data = dict(record.data)
            duplicate_data["pid"] = None
            duplicate_data["state"] = "AMBIGUOUS"
            collapsed[record.key] = SocketRecord(
                kind=record.kind,
                key=record.key,
                data=duplicate_data,
                ambiguous=True,
            )
        return collapsed

    def _observed(self, record: SocketRecord) -> Observation:
        return Observation(
            event_type=f"network.{record.kind}_observed",
            source=self.source,
            data=record.data,
        )

    def _transition(
        self, record: SocketRecord, transition: Literal["opened", "closed"]
    ) -> Observation:
        return Observation(
            event_type=f"network.{record.kind}_{transition}",
            source=self.source,
            data=record.data,
        )

    @staticmethod
    def _address(address: Any) -> tuple[str, int]:
        if not address:
            raise ValueError("socket address is missing")
        try:
            raw_ip, raw_port = address.ip, address.port
        except AttributeError:
            raw_ip, raw_port = address[0], address[1]
        ip = str(ipaddress.ip_address(str(raw_ip)))
        port = int(raw_port)
        if not 0 <= port <= 65535:
            raise ValueError("socket port is out of range")
        return ip, port

    def _load_state(self) -> dict[str, SocketRecord] | None:
        if self._state_path is None:
            return None if self._memory_state is None else dict(self._memory_state)
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            if raw.get("version") != 1:
                return None
            records = [
                SocketRecord(
                    kind=item["kind"],
                    key=str(item["key"]),
                    data=dict(item["data"]),
                    ambiguous=bool(item.get("ambiguous", False)),
                )
                for item in raw["sockets"]
                if item["kind"] in {"listener", "connection"}
            ]
            return {record.key: record for record in records}
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _save_state(self, sockets: dict[str, SocketRecord]) -> None:
        if self._state_path is None:
            self._memory_state = dict(sockets)
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = {
            "version": 1,
            "sockets": [
                {
                    "kind": record.kind,
                    "key": record.key,
                    "data": record.data,
                    "ambiguous": record.ambiguous,
                }
                for record in sorted(sockets.values(), key=lambda item: item.key)
            ],
        }
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self._state_path.parent,
            prefix=f".{self._state_path.name}.",
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, self._state_path)
            directory_descriptor = os.open(self._state_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        self._memory_state = dict(sockets)
