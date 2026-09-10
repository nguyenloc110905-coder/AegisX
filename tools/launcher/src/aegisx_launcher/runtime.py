import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from aegisx_launcher.commands import CommandResult, CommandRunner
from aegisx_launcher.compose import ComposeProvider, discover_compose_providers

API_READY_URL = "http://127.0.0.1:8000/api/v1/health/ready"


class Process(Protocol):
    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...


class Runner(Protocol):
    def executable_exists(self, executable: str) -> bool: ...

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        timeout: float | None = None,
    ) -> CommandResult: ...


def _probe_url(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310
            return 200 <= int(response.status) < 300
    except (OSError, urllib.error.URLError):
        return False


def wait_for_readiness(
    url: str,
    timeout: float,
    *,
    probe: Callable[[str], bool] = _probe_url,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> bool:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if probe(url):
            return True
        sleep(0.25)
    return False


def _spawn_process(argv: tuple[str, ...], *, cwd: Path) -> Process:
    return subprocess.Popen(argv, cwd=cwd, start_new_session=True)  # noqa: S603


class AegisXRuntime:
    def __init__(
        self,
        root: Path,
        env_file: Path,
        *,
        runner: Runner | None = None,
        providers: tuple[ComposeProvider, ...] | None = None,
        process_factory: Callable[..., Process] = _spawn_process,
        readiness_waiter: Callable[[str, float], bool] = wait_for_readiness,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._root = root
        self._env_file = env_file
        self._runner = runner or CommandRunner()
        self._configured_providers = providers
        self._process_factory = process_factory
        self._readiness_waiter = readiness_waiter
        self._sleep = sleep

    def _providers(self) -> tuple[ComposeProvider, ...]:
        if self._configured_providers is not None:
            return self._configured_providers
        return discover_compose_providers(self._runner, self._root, self._env_file)

    def doctor(self) -> int:
        if not self._runner.executable_exists("uv"):
            print("[failed] uv is not available on PATH")
            return 1
        providers = self._providers()
        if not providers:
            print("[failed] no valid Docker or Podman Compose provider")
            return 1
        print(f"[ok] project: {self._root}")
        print(f"[ok] environment: {self._env_file.name}")
        print(f"[ok] compose: {providers[0].name}")
        return 0

    def stop(self) -> int:
        for provider in self._providers():
            result = self._runner.run(
                provider.argv(self._env_file, "stop", "postgres"),
                cwd=self._root,
                timeout=60,
            )
            if result.returncode == 0:
                print(f"[ok] stopped PostgreSQL using {provider.name}")
                return 0
        print("[failed] could not stop PostgreSQL with any Compose provider")
        return 1

    def run(self) -> int:
        if not self._runner.executable_exists("uv"):
            print("[failed] uv is required; install it from https://docs.astral.sh/uv/")
            return 1
        providers = self._providers()
        if not providers:
            print("[failed] no valid Docker or Podman Compose provider")
            return 1

        provider: ComposeProvider | None = None
        postgres_started_here = False
        for candidate in providers:
            status = self._runner.run(
                candidate.argv(
                    self._env_file, "ps", "--services", "--status", "running", "postgres"
                ),
                cwd=self._root,
                timeout=30,
            )
            was_running = status.returncode == 0 and "postgres" in status.stdout.splitlines()
            started = self._runner.run(
                candidate.argv(self._env_file, "up", "-d", "--wait", "postgres"),
                cwd=self._root,
                timeout=120,
            )
            if started.returncode == 0:
                provider = candidate
                postgres_started_here = not was_running
                print(f"[ok] PostgreSQL ready via {candidate.name}")
                break
            if not was_running:
                self._runner.run(
                    candidate.argv(self._env_file, "stop", "postgres"),
                    cwd=self._root,
                    timeout=30,
                )
            print(f"[retry] {candidate.name} could not start PostgreSQL")
        if provider is None:
            print("[failed] PostgreSQL could not be started")
            return 1

        api_process: Process | None = None
        agent_process: Process | None = None
        try:
            setup_commands = (
                ("uv", "sync", "--project", "apps/api", "--all-groups"),
                ("uv", "sync", "--project", "apps/agent", "--all-groups"),
                (
                    "uv",
                    "run",
                    "--project",
                    "apps/api",
                    "alembic",
                    "-c",
                    "apps/api/alembic.ini",
                    "upgrade",
                    "head",
                ),
            )
            for argv in setup_commands:
                result = self._runner.run(argv, cwd=self._root, timeout=300)
                if result.returncode != 0:
                    print(f"[failed] setup command exited with code {result.returncode}: {argv[1]}")
                    return 1

            api_argv = (
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
            )
            api_process = self._process_factory(api_argv, cwd=self._root)
            if not self._readiness_waiter(API_READY_URL, 30):
                print("[failed] API readiness timed out after 30 seconds")
                return 1

            agent_argv = ("uv", "run", "--project", "apps/agent", "aegisx-agent", "run")
            agent_process = self._process_factory(agent_argv, cwd=self._root)
            print("[ok] AegisX is running; press Ctrl+C to stop")

            while True:
                api_code = api_process.poll()
                if api_code is not None:
                    return api_code
                agent_code = agent_process.poll()
                if agent_code is not None:
                    return agent_code
                self._sleep(0.25)
        except KeyboardInterrupt:
            return 130
        finally:
            self._terminate(agent_process)
            self._terminate(api_process)
            if postgres_started_here:
                self._runner.run(
                    provider.argv(self._env_file, "stop", "postgres"),
                    cwd=self._root,
                    timeout=60,
                )

    @staticmethod
    def _terminate(process: Process | None) -> None:
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except (TimeoutError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=5)
