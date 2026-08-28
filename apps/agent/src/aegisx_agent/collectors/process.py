import json
import os
from collections.abc import Callable, Iterable
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


class ProcessCollector:
    source = "process_collector"

    def __init__(
        self,
        process_iter: Callable[..., Iterable[Any]] = psutil.process_iter,
        max_processes: int = 40,
        max_command_args: int = 64,
        max_command_chars: int = 4096,
        state_path: Path | None = None,
    ) -> None:
        self._process_iter = process_iter
        self._max_processes = max_processes
        self._max_command_args = max_command_args
        self._max_command_chars = max_command_chars
        self._state_path = state_path
        self._memory_state: set[str] | None = None

    def collect(self) -> list[Observation]:
        observations: list[Observation] = []
        previous = self._load_state()
        current: set[str] = set()
        collected = 0
        processes = self._process_iter(attrs=PROCESS_ATTRIBUTES, ad_value=None)
        for process in processes:
            if collected >= self._max_processes:
                break
            try:
                info = process.info
                pid = int(info["pid"])
                process_key = self._process_key(pid, info.get("create_time"))
                current.add(process_key)
                started_at = self._started_at(info.get("create_time"))
                command_line = self._bound_command_line(info.get("cmdline"))
                if previous is not None and process_key not in previous:
                    observations.append(
                        Observation(
                            event_type="process.started",
                            source=self.source,
                            data={
                                "pid": pid,
                                "ppid": int(info.get("ppid") or 0),
                                "name": str(info.get("name") or "unknown"),
                                "executable": info.get("exe"),
                                "user": info.get("username"),
                                "command_line": command_line,
                                "started_at": started_at,
                            },
                        )
                    )
                memory_info = info.get("memory_info")
                observations.append(
                    Observation(
                        event_type="process.resource_usage",
                        source=self.source,
                        data={
                            "pid": pid,
                            "cpu_percent": float(info.get("cpu_percent") or 0.0),
                            "memory_bytes": int(getattr(memory_info, "rss", 0)),
                        },
                    )
                )
                collected += 1
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        self._save_state(current)
        return observations

    def _load_state(self) -> set[str] | None:
        if self._state_path is None:
            return None if self._memory_state is None else set(self._memory_state)
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            keys = raw["process_keys"]
            if raw.get("version") != 1 or not isinstance(keys, list):
                return None
            return {str(key) for key in keys}
        except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _save_state(self, process_keys: set[str]) -> None:
        self._memory_state = set(process_keys)
        if self._state_path is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self._state_path, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "process_keys": sorted(process_keys)}, stream)
            stream.write("\n")

    @staticmethod
    def _process_key(pid: int, create_time: Any) -> str:
        return f"{pid}:{create_time!r}"

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

    @staticmethod
    def _started_at(raw_timestamp: Any) -> str | None:
        if not isinstance(raw_timestamp, (int, float)):
            return None
        return datetime.fromtimestamp(raw_timestamp, tz=UTC).isoformat()
