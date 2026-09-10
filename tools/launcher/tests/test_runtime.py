import os
import sys
from collections.abc import Callable
from pathlib import Path

from aegisx_launcher.commands import CommandResult
from aegisx_launcher.compose import ComposeProvider
from aegisx_launcher.runtime import AegisXRuntime, _spawn_process, wait_for_readiness


class FakeRunner:
    def __init__(self, handler: Callable[[tuple[str, ...]], tuple[int, str, str]]) -> None:
        self.handler = handler
        self.calls: list[tuple[str, ...]] = []

    def executable_exists(self, executable: str) -> bool:
        return executable in {"uv", "docker", "podman", "systemctl"}

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        timeout: float | None = None,
    ) -> CommandResult:
        self.calls.append(argv)
        code, stdout, stderr = self.handler(argv)
        return CommandResult(argv, code, stdout, stderr)


class FakeProcess:
    def __init__(self, polls: list[int | None]) -> None:
        self._polls = iter(polls)
        self._last: int | None = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        try:
            self._last = next(self._polls)
        except StopIteration:
            pass
        return self._last

    def terminate(self) -> None:
        self.terminated = True
        self._last = 0

    def wait(self, timeout: float | None = None) -> int:
        if self._last is None:
            raise TimeoutError
        return self._last

    def kill(self) -> None:
        self.killed = True
        self._last = -9


class FakeProcessFactory:
    def __init__(self, processes: list[FakeProcess]) -> None:
        self.processes = iter(processes)
        self.calls: list[tuple[str, ...]] = []
        self.quiet_calls: list[bool] = []

    def __call__(self, argv: tuple[str, ...], *, cwd: Path, quiet: bool = False) -> FakeProcess:
        self.calls.append(argv)
        self.quiet_calls.append(quiet)
        return next(self.processes)


def _providers() -> tuple[ComposeProvider, ...]:
    return (ComposeProvider(("docker", "compose")), ComposeProvider(("podman", "compose")))


def test_spawned_process_remains_in_launchers_terminal_process_group(tmp_path: Path) -> None:
    process = _spawn_process(
        (sys.executable, "-c", "import time; time.sleep(30)"),
        cwd=tmp_path,
    )

    try:
        assert os.getsid(process.pid) == os.getsid(0)
        assert os.getpgid(process.pid) == os.getpgrp()
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_runtime_falls_back_provider_and_starts_agent_only_after_readiness(tmp_path: Path) -> None:
    def command(argv: tuple[str, ...]) -> tuple[int, str, str]:
        if argv[:2] == ("docker", "compose") and "up" in argv:
            return 1, "", "daemon denied"
        return 0, "", ""

    runner = FakeRunner(command)
    api = FakeProcess([None, 9])
    agent = FakeProcess([None, None])
    processes = FakeProcessFactory([api, agent])
    readiness_calls: list[str] = []

    def ready(url: str, timeout: float) -> bool:
        readiness_calls.append(url)
        return True

    runtime = AegisXRuntime(
        tmp_path,
        tmp_path / ".env.example",
        runner=runner,
        providers=_providers(),
        process_factory=processes,
        readiness_waiter=ready,
        sleep=lambda _: None,
    )

    assert runtime.run(show_ui=False) == 9
    assert any(call[:2] == ("docker", "compose") and "up" in call for call in runner.calls)
    assert any(call[:2] == ("podman", "compose") and "up" in call for call in runner.calls)
    assert runner.calls.index(("uv", "sync", "--project", "apps/api", "--all-groups")) < len(
        runner.calls
    )
    assert readiness_calls == ["http://127.0.0.1:8000/health/ready"]
    assert processes.calls == [
        (
            "uv",
            "run",
            "--project",
            "apps/api",
            "uvicorn",
            "aegisx_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ),
        ("uv", "run", "--project", "apps/agent", "aegisx-agent", "run"),
    ]
    assert agent.terminated


def test_readiness_failure_prevents_agent_start_and_cleans_up(tmp_path: Path) -> None:
    runner = FakeRunner(lambda _: (0, "", ""))
    api = FakeProcess([None])
    processes = FakeProcessFactory([api])
    runtime = AegisXRuntime(
        tmp_path,
        tmp_path / ".env",
        runner=runner,
        providers=(ComposeProvider(("podman", "compose")),),
        process_factory=processes,
        readiness_waiter=lambda _url, _timeout: False,
    )

    assert runtime.run() == 1
    assert len(processes.calls) == 1
    assert api.terminated
    assert any("stop" in call and "postgres" in call for call in runner.calls)


def test_runtime_runs_console_in_foreground_and_cleans_up_background_children(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(lambda _: (0, "", ""))
    api = FakeProcess([None, None])
    agent = FakeProcess([None, None])
    console = FakeProcess([None, 0])
    processes = FakeProcessFactory([api, agent, console])
    runtime = AegisXRuntime(
        tmp_path,
        tmp_path / ".env",
        runner=runner,
        providers=(ComposeProvider(("podman", "compose")),),
        process_factory=processes,
        readiness_waiter=lambda _url, _timeout: True,
        sleep=lambda _: None,
    )

    assert runtime.run() == 0
    assert processes.calls[-1] == (
        "uv",
        "run",
        "--project",
        "apps/api",
        "aegisx-console",
    )
    assert processes.quiet_calls == [True, True, False]
    assert api.terminated and agent.terminated


def test_podman_runtime_starts_user_socket_once_then_retries(tmp_path: Path) -> None:
    socket_started = False

    def command(argv: tuple[str, ...]) -> tuple[int, str, str]:
        nonlocal socket_started
        if argv[:3] == ("systemctl", "--user", "start"):
            socket_started = True
            return 0, "", ""
        if argv[:2] == ("podman", "compose") and "up" in argv and not socket_started:
            return 1, "", "socket unavailable"
        return 0, "", ""

    runner = FakeRunner(command)
    api = FakeProcess([4])
    agent = FakeProcess([None])
    runtime = AegisXRuntime(
        tmp_path,
        tmp_path / ".env",
        runner=runner,
        providers=(ComposeProvider(("podman", "compose")),),
        process_factory=FakeProcessFactory([api, agent]),
        readiness_waiter=lambda _url, _timeout: True,
        sleep=lambda _: None,
    )

    assert runtime.run(show_ui=False) == 4
    assert ("systemctl", "--user", "start", "podman.socket") in runner.calls
    podman_up_calls = [
        call for call in runner.calls if call[:2] == ("podman", "compose") and "up" in call
    ]
    assert len(podman_up_calls) == 2


def test_existing_postgres_is_not_stopped_when_child_fails(tmp_path: Path) -> None:
    def command(argv: tuple[str, ...]) -> tuple[int, str, str]:
        if "ps" in argv:
            return 0, "postgres\n", ""
        return 0, "", ""

    runner = FakeRunner(command)
    api = FakeProcess([3])
    agent = FakeProcess([None])
    runtime = AegisXRuntime(
        tmp_path,
        tmp_path / ".env",
        runner=runner,
        providers=(ComposeProvider(("podman", "compose")),),
        process_factory=FakeProcessFactory([api, agent]),
        readiness_waiter=lambda _url, _timeout: True,
        sleep=lambda _: None,
    )

    assert runtime.run(show_ui=False) == 3
    assert not any("stop" in call and "postgres" in call for call in runner.calls)
    assert agent.terminated


def test_keyboard_interrupt_stops_children_and_started_postgres(tmp_path: Path) -> None:
    runner = FakeRunner(lambda _: (0, "", ""))
    api = FakeProcess([None])
    agent = FakeProcess([None])

    def interrupt(_: float) -> None:
        raise KeyboardInterrupt

    runtime = AegisXRuntime(
        tmp_path,
        tmp_path / ".env",
        runner=runner,
        providers=(ComposeProvider(("podman", "compose")),),
        process_factory=FakeProcessFactory([api, agent]),
        readiness_waiter=lambda _url, _timeout: True,
        sleep=interrupt,
    )

    assert runtime.run(show_ui=False) == 130
    assert api.terminated and agent.terminated
    assert any("stop" in call and "postgres" in call for call in runner.calls)


def test_doctor_fails_when_uv_or_compose_is_unavailable(tmp_path: Path) -> None:
    runner = FakeRunner(lambda _: (0, "", ""))
    runner.executable_exists = lambda _executable: False  # type: ignore[method-assign]
    runtime = AegisXRuntime(tmp_path, tmp_path / ".env", runner=runner, providers=())

    assert runtime.doctor() == 1


def test_stop_uses_first_provider_that_succeeds(tmp_path: Path) -> None:
    def command(argv: tuple[str, ...]) -> tuple[int, str, str]:
        return (1, "", "failed") if argv[0] == "docker" else (0, "", "")

    runner = FakeRunner(command)
    runtime = AegisXRuntime(
        tmp_path,
        tmp_path / ".env",
        runner=runner,
        providers=_providers(),
    )

    assert runtime.stop() == 0
    stop_calls = [call for call in runner.calls if "stop" in call]
    assert [call[0] for call in stop_calls] == ["docker", "podman"]


def test_wait_for_readiness_stops_at_deadline() -> None:
    clock = iter([0.0, 0.0, 0.5, 1.0])
    attempts: list[str] = []

    result = wait_for_readiness(
        "http://127.0.0.1/ready",
        timeout=1.0,
        probe=lambda url: attempts.append(url) or False,
        sleep=lambda _: None,
        monotonic=lambda: next(clock),
    )

    assert result is False
    assert attempts == ["http://127.0.0.1/ready", "http://127.0.0.1/ready"]


def test_wait_for_readiness_returns_after_success() -> None:
    outcomes = iter([False, True])

    assert wait_for_readiness(
        "http://127.0.0.1/ready",
        timeout=5,
        probe=lambda _url: next(outcomes),
        sleep=lambda _: None,
        monotonic=lambda: 0.0,
    )
