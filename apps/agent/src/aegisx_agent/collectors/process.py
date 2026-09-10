import json
import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from aegisx_agent.events import Observation

PROCESS_ATTRIBUTES = [
    "pid",
    "ppid",
    "name",
    "exe",
    "username",
    "cmdline",
    "cpu_percent",
    "memory_info",
    "create_time",
]


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    create_time: float

    @property
    def key(self) -> str:
        return f"{self.pid}:{self.create_time!r}"

    @property
    def started_at(self) -> str:
        return datetime.fromtimestamp(self.create_time, tz=UTC).isoformat()


class ProcessCollector:
    source = "process_collector"

    def __init__(
        self,
        process_iter: Callable[..., Iterable[Any]] = psutil.process_iter,
        max_processes: int = 40,
        max_command_args: int = 64,
        max_command_chars: int = 4096,
        state_path: Path | None = None,
        emit_resource_usage: bool = False,
    ) -> None:
        self._process_iter = process_iter
        self._max_processes = max_processes
        self._max_command_args = max_command_args
        self._max_command_chars = max_command_chars
        self._state_path = state_path
        self._emit_resource_usage = emit_resource_usage
        self._memory_state: dict[str, ProcessIdentity] | None = None

    def collect(self) -> list[Observation]:
        previous = self._load_state()
        current: dict[str, ProcessIdentity] = {}
        bounded_records: list[tuple[ProcessIdentity, dict[str, Any]]] = []
        snapshot_complete = True
        try:
            processes = self._process_iter(attrs=PROCESS_ATTRIBUTES, ad_value=None)
            for process in processes:
                try:
                    info = process.info
                    identity = self._identity(info)
                    current[identity.key] = identity
                    if len(bounded_records) < self._max_processes:
                        bounded_records.append((identity, info))
                except (
                    KeyError,
                    TypeError,
                    ValueError,
                    psutil.AccessDenied,
                    psutil.NoSuchProcess,
                    psutil.ZombieProcess,
                ):
                    snapshot_complete = False
        except (psutil.AccessDenied, psutil.Error):
            return []

        observations: list[Observation] = []
        for identity, info in bounded_records:
            if snapshot_complete and previous is not None and identity.key not in previous:
                observations.append(self._started_observation(identity, info))
            if self._emit_resource_usage:
                observations.append(self._resource_observation(identity.pid, info))

        if not snapshot_complete:
            return observations

        if previous is not None:
            exited_keys = sorted(previous.keys() - current.keys())[: self._max_processes]
            for process_key in exited_keys:
                identity = previous[process_key]
                observations.append(
                    Observation(
                        event_type="process.exited",
                        source=self.source,
                        data={"pid": identity.pid, "started_at": identity.started_at},
                    )
                )
        self._save_state(current)
        return observations

    @staticmethod
    def _identity(info: dict[str, Any]) -> ProcessIdentity:
        pid = int(info["pid"])
        create_time = info.get("create_time")
        if pid <= 0 or not isinstance(create_time, (int, float)):
            raise ValueError("process lifecycle identity requires positive pid and create_time")
        return ProcessIdentity(pid=pid, create_time=float(create_time))

    def _started_observation(self, identity: ProcessIdentity, info: dict[str, Any]) -> Observation:
        return Observation(
            event_type="process.started",
            source=self.source,
            data={
                "pid": identity.pid,
                "ppid": int(info.get("ppid") or 0),
                "name": str(info.get("name") or "unknown"),
                "executable": info.get("exe"),
                "user": info.get("username"),
                "command_line": self._bound_command_line(info.get("cmdline")),
                "started_at": identity.started_at,
            },
        )

    def _resource_observation(self, pid: int, info: dict[str, Any]) -> Observation:
        memory_info = info.get("memory_info")
        return Observation(
            event_type="process.resource_usage",
            source=self.source,
            data={
                "pid": pid,
                "cpu_percent": float(info.get("cpu_percent") or 0.0),
                "memory_bytes": int(getattr(memory_info, "rss", 0)),
            },
        )

    def _load_state(self) -> dict[str, ProcessIdentity] | None:
        if self._state_path is None:
            return None if self._memory_state is None else dict(self._memory_state)
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            if raw.get("version") == 2:
                identities = [
                    ProcessIdentity(pid=int(item["pid"]), create_time=float(item["create_time"]))
                    for item in raw["processes"]
                ]
            elif raw.get("version") == 1:
                identities = [
                    self._identity_from_legacy_key(str(key)) for key in raw["process_keys"]
                ]
            else:
                return None
            return {identity.key: identity for identity in identities}
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _identity_from_legacy_key(process_key: str) -> ProcessIdentity:
        raw_pid, separator, raw_create_time = process_key.partition(":")
        if not separator:
            raise ValueError("invalid legacy process identity")
        return ProcessIdentity(pid=int(raw_pid), create_time=float(raw_create_time))

    def _save_state(self, processes: dict[str, ProcessIdentity]) -> None:
        if self._state_path is None:
            self._memory_state = dict(processes)
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = {
            "version": 2,
            "processes": [
                {"pid": identity.pid, "create_time": identity.create_time}
                for identity in sorted(
                    processes.values(), key=lambda item: (item.pid, item.create_time)
                )
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
        self._memory_state = dict(processes)

    def _bound_command_line(self, raw_command: Any) -> list[str]:
        if not isinstance(raw_command, (list, tuple)):
            return []
        remaining = self._max_command_chars
        bounded: list[str] = []
        for raw_argument in raw_command[: self._max_command_args]:
            if remaining <= 0:
                break
            argument = str(raw_argument)[:remaining]
            bounded.append(argument)
            remaining -= len(argument)
        return bounded
