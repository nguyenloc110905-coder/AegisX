import sys
from pathlib import Path

import pytest

from aegisx_launcher.commands import CommandResult, CommandRunner
from aegisx_launcher.compose import (
    ComposeConfigurationError,
    ComposeProvider,
    discover_compose_providers,
    parse_compose_override,
)


class FakeRunner:
    def __init__(
        self,
        *,
        available: set[str],
        results: dict[tuple[str, ...], CommandResult],
    ) -> None:
        self.available = available
        self.results = results
        self.calls: list[tuple[str, ...]] = []

    def executable_exists(self, executable: str) -> bool:
        return executable in self.available

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        timeout: float | None = None,
    ) -> CommandResult:
        self.calls.append(argv)
        return self.results.get(argv, CommandResult(argv, 0, "", ""))


def test_command_runner_executes_argv_without_a_shell(tmp_path: Path) -> None:
    result = CommandRunner().run(
        (sys.executable, "-c", "print('safe output')"),
        cwd=tmp_path,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "safe output"
    assert result.argv == (sys.executable, "-c", "print('safe output')")


def test_command_result_bounds_diagnostic_output() -> None:
    result = CommandResult(("tool",), 1, "x" * 500, "secret detail" + "y" * 500)

    diagnostic = result.diagnostic(limit=80)

    assert len(diagnostic) <= 80
    assert diagnostic.endswith("...")


def test_override_is_parsed_as_argv_not_shell_source() -> None:
    assert parse_compose_override("podman compose --log-level warning") == (
        "podman",
        "compose",
        "--log-level",
        "warning",
    )


@pytest.mark.parametrize("raw", ["", "   ", "docker 'unterminated"])
def test_invalid_override_fails_clearly(raw: str) -> None:
    with pytest.raises(ComposeConfigurationError):
        parse_compose_override(raw)


def test_provider_builds_exact_repository_scoped_command(tmp_path: Path) -> None:
    provider = ComposeProvider(("podman", "compose"))
    env_file = tmp_path / ".env.example"

    assert provider.argv(env_file, "up", "-d", "postgres") == (
        "podman",
        "compose",
        "--env-file",
        str(env_file),
        "up",
        "-d",
        "postgres",
    )


def test_discovery_keeps_valid_providers_in_docker_then_podman_order(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.example"
    docker_config = ("docker", "compose", "--env-file", str(env_file), "config", "--quiet")
    podman_config = ("podman", "compose", "--env-file", str(env_file), "config", "--quiet")
    runner = FakeRunner(
        available={"docker", "podman"},
        results={
            docker_config: CommandResult(docker_config, 0, "", ""),
            podman_config: CommandResult(podman_config, 0, "", ""),
        },
    )

    providers = discover_compose_providers(runner, tmp_path, env_file)

    assert [provider.command for provider in providers] == [
        ("docker", "compose"),
        ("podman", "compose"),
    ]


def test_discovery_skips_missing_and_config_rejected_providers(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    docker_config = ("docker", "compose", "--env-file", str(env_file), "config", "--quiet")
    runner = FakeRunner(
        available={"docker"},
        results={docker_config: CommandResult(docker_config, 14, "", "malformed compose")},
    )

    assert discover_compose_providers(runner, tmp_path, env_file) == ()


def test_override_is_the_only_provider_considered(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    custom_config = ("custom", "compose", "--env-file", str(env_file), "config", "--quiet")
    runner = FakeRunner(
        available={"custom", "docker", "podman"},
        results={custom_config: CommandResult(custom_config, 0, "", "")},
    )

    providers = discover_compose_providers(
        runner,
        tmp_path,
        env_file,
        override="custom compose",
    )

    assert [provider.command for provider in providers] == [("custom", "compose")]
    assert runner.calls == [custom_config]
