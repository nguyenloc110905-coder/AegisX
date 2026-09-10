from collections.abc import Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psutil

from aegisx_agent.collectors.process import ProcessCollector


class FakeProcess:
    def __init__(
        self,
        info: dict[str, Any] | None = None,
        error: Exception | None = None,
        pid: int | None = None,
    ) -> None:
        self._info = info
        self._error = error
        self.pid = pid if pid is not None else int((info or {}).get("pid", 0))

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


def process_info(
    pid: int,
    command_line: list[str] | None = None,
    *,
    create_time: float = 1_700_000_000.0,
) -> dict[str, Any]:
    return {
        "pid": pid,
        "ppid": 1,
        "name": "python",
        "exe": "/usr/bin/python3",
        "username": "student",
        "cmdline": command_line or ["python3", "demo.py"],
        "cpu_percent": 12.5,
        "memory_info": SimpleNamespace(rss=4096),
        "create_time": create_time,
    }


def test_process_collector_baselines_then_emits_only_new_processes(tmp_path: Path) -> None:
    processes = [FakeProcess(process_info(42))]
    collector = ProcessCollector(
        process_iter=iterator(processes), state_path=tmp_path / "process-state.json"
    )

    baseline = collector.collect()
    restarted_collector = ProcessCollector(
        process_iter=iterator(processes), state_path=tmp_path / "process-state.json"
    )
    unchanged = restarted_collector.collect()
    processes.append(FakeProcess(process_info(43)))
    changed = restarted_collector.collect()

    assert baseline == []
    assert unchanged == []
    assert [event.event_type for event in changed] == ["process.started"]
    assert changed[0].data["pid"] == 43
    assert changed[0].data["command_line"] == ["python3", "demo.py"]


def test_process_resource_usage_is_opt_in(tmp_path: Path) -> None:
    collector = ProcessCollector(
        process_iter=iterator([FakeProcess(process_info(42))]),
        state_path=tmp_path / "process-state.json",
        emit_resource_usage=True,
    )

    events = collector.collect()

    assert [event.event_type for event in events] == ["process.resource_usage"]
    assert events[0].data == {"pid": 42, "cpu_percent": 12.5, "memory_bytes": 4096}


def test_process_collector_skips_inaccessible_and_vanished_processes(tmp_path: Path) -> None:
    processes = [
        FakeProcess(error=psutil.AccessDenied(pid=1)),
        FakeProcess(error=psutil.NoSuchProcess(pid=2)),
        FakeProcess(process_info(3)),
    ]

    events = ProcessCollector(
        process_iter=iterator(processes), state_path=tmp_path / "process-state.json"
    ).collect()

    assert events == []


def test_process_collector_emits_exit_only_after_complete_absence(tmp_path: Path) -> None:
    state_path = tmp_path / "process-state.json"
    processes = [FakeProcess(process_info(42))]
    collector = ProcessCollector(process_iter=iterator(processes), state_path=state_path)

    collector.collect()
    unchanged = collector.collect()
    processes.clear()
    exited = collector.collect()
    repeated_empty = collector.collect()

    assert "process.exited" not in [event.event_type for event in unchanged]
    assert [(event.event_type, event.data) for event in exited] == [
        (
            "process.exited",
            {"pid": 42, "started_at": "2023-11-14T22:13:20+00:00"},
        )
    ]
    assert repeated_empty == []


def test_process_collector_does_not_infer_exit_from_failed_lookup(tmp_path: Path) -> None:
    state_path = tmp_path / "process-state.json"
    processes = [FakeProcess(process_info(42))]
    collector = ProcessCollector(process_iter=iterator(processes), state_path=state_path)
    collector.collect()

    processes[:] = [FakeProcess(error=psutil.NoSuchProcess(pid=42), pid=42)]
    failed = collector.collect()
    processes[:] = [FakeProcess(process_info(42))]
    recovered = collector.collect()

    assert failed == []
    assert recovered == []


def test_process_collector_does_not_update_baseline_without_create_time(tmp_path: Path) -> None:
    state_path = tmp_path / "process-state.json"
    processes = [FakeProcess(process_info(42))]
    collector = ProcessCollector(process_iter=iterator(processes), state_path=state_path)
    collector.collect()

    incomplete = process_info(42)
    incomplete["create_time"] = None
    processes[:] = [FakeProcess(incomplete)]
    assert collector.collect() == []

    processes[:] = [FakeProcess(process_info(42))]
    assert collector.collect() == []


def test_process_collector_pid_reuse_emits_old_exit_and_new_start(tmp_path: Path) -> None:
    state_path = tmp_path / "process-state.json"
    old = FakeProcess(process_info(42, create_time=1_700_000_000.0))
    replacement = FakeProcess(process_info(42, create_time=1_700_000_100.0))
    processes = [old]
    collector = ProcessCollector(process_iter=iterator(processes), state_path=state_path)
    collector.collect()

    processes[:] = [replacement]
    events = collector.collect()

    assert {event.event_type for event in events} == {"process.started", "process.exited"}
    assert next(event for event in events if event.event_type == "process.exited").data == {
        "pid": 42,
        "started_at": "2023-11-14T22:13:20+00:00",
    }
    assert (
        next(event for event in events if event.event_type == "process.started").data["started_at"]
        == "2023-11-14T22:15:00+00:00"
    )


def test_process_collector_restart_reads_persisted_exit_baseline(tmp_path: Path) -> None:
    state_path = tmp_path / "process-state.json"
    ProcessCollector(
        process_iter=iterator([FakeProcess(process_info(42))]), state_path=state_path
    ).collect()

    events = ProcessCollector(process_iter=iterator([]), state_path=state_path).collect()

    assert [event.event_type for event in events] == ["process.exited"]


def test_process_collector_output_cap_does_not_make_identity_snapshot_incomplete(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "process-state.json"
    processes = [FakeProcess(process_info(42)), FakeProcess(process_info(43))]
    collector = ProcessCollector(
        process_iter=iterator(processes), max_processes=1, state_path=state_path
    )
    baseline = collector.collect()

    unchanged = collector.collect()
    processes[:] = [FakeProcess(process_info(42))]
    exited = collector.collect()

    assert baseline == []
    assert unchanged == []
    assert [event.data["pid"] for event in exited if event.event_type == "process.exited"] == [43]


def test_process_collector_bounds_exit_output_without_truncating_state(tmp_path: Path) -> None:
    state_path = tmp_path / "process-state.json"
    processes = [FakeProcess(process_info(pid)) for pid in (41, 42, 43)]
    collector = ProcessCollector(
        process_iter=iterator(processes), max_processes=1, state_path=state_path
    )
    collector.collect()
    processes.clear()

    exited = collector.collect()

    assert len(exited) == 1
    assert exited[0].event_type == "process.exited"


def test_process_collector_bounds_processes_and_command_line(tmp_path: Path) -> None:
    long_command = ["x" * 200 for _ in range(100)]
    processes = [FakeProcess(process_info(pid, long_command)) for pid in range(1, 5)]
    collector = ProcessCollector(
        process_iter=iterator(processes),
        max_processes=2,
        max_command_args=3,
        max_command_chars=128,
        state_path=tmp_path / "process-state.json",
    )

    collector.collect()
    processes[:] = [processes[0], FakeProcess(process_info(99, long_command))]
    events = collector.collect()

    lifecycle = [event for event in events if event.event_type == "process.started"]
    assert len(lifecycle) == 1
    assert all(len(event.data["command_line"]) <= 3 for event in lifecycle)
    assert all(
        sum(len(argument) for argument in event.data["command_line"]) <= 128 for event in lifecycle
    )
