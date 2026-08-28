from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any

import psutil

from aegisx_agent.collectors.process import ProcessCollector


class FakeProcess:
    def __init__(self, info: dict[str, Any] | None = None, error: Exception | None = None):
        self._info = info
        self._error = error

    @property
    def info(self) -> dict[str, Any]:
        if self._error:
            raise self._error
        assert self._info is not None
        return self._info


def iterator(processes: list[FakeProcess]):
    def process_iter(*, attrs: list[str], ad_value: None) -> Iterable[FakeProcess]:
        assert "pid" in attrs
        assert ad_value is None
        return processes

    return process_iter


def process_info(pid: int, command_line: list[str] | None = None) -> dict[str, Any]:
    return {
        "pid": pid,
        "ppid": 1,
        "name": "python",
        "exe": "/usr/bin/python3",
        "username": "student",
        "cmdline": command_line or ["python3", "demo.py"],
        "cpu_percent": 12.5,
        "memory_info": SimpleNamespace(rss=4096),
        "create_time": 1_700_000_000.0,
    }


def test_process_collector_emits_lifecycle_and_resource_events() -> None:
    collector = ProcessCollector(process_iter=iterator([FakeProcess(process_info(42))]))

    events = collector.collect()

    assert [event.event_type for event in events] == [
        "process.started",
        "process.resource_usage",
    ]
    assert events[0].data["pid"] == 42
    assert events[0].data["command_line"] == ["python3", "demo.py"]
    assert events[1].data == {"pid": 42, "cpu_percent": 12.5, "memory_bytes": 4096}


def test_process_collector_skips_inaccessible_and_vanished_processes() -> None:
    processes = [
        FakeProcess(error=psutil.AccessDenied(pid=1)),
        FakeProcess(error=psutil.NoSuchProcess(pid=2)),
        FakeProcess(process_info(3)),
    ]

    events = ProcessCollector(process_iter=iterator(processes)).collect()

    assert len(events) == 2
    assert all(event.data["pid"] == 3 for event in events)


def test_process_collector_bounds_processes_and_command_line() -> None:
    long_command = ["x" * 200 for _ in range(100)]
    processes = [FakeProcess(process_info(pid, long_command)) for pid in range(1, 5)]
    collector = ProcessCollector(
        process_iter=iterator(processes),
        max_processes=2,
        max_command_args=3,
        max_command_chars=128,
    )

    events = collector.collect()

    lifecycle = [event for event in events if event.event_type == "process.started"]
    assert len(lifecycle) == 2
    assert all(len(event.data["command_line"]) <= 3 for event in lifecycle)
    assert all(
        sum(len(argument) for argument in event.data["command_line"]) <= 128
        for event in lifecycle
    )
