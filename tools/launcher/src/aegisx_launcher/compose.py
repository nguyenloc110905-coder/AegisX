import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from aegisx_launcher.commands import CommandResult


class ComposeConfigurationError(RuntimeError):
    """Raised when an explicit Compose command is malformed."""


class CommandExecutor(Protocol):
    def executable_exists(self, executable: str) -> bool: ...

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        timeout: float | None = None,
    ) -> CommandResult: ...


@dataclass(frozen=True)
class ComposeProvider:
    command: tuple[str, ...]

    @property
    def name(self) -> str:
        return " ".join(self.command)

    def argv(self, env_file: Path, *arguments: str) -> tuple[str, ...]:
        return (*self.command, "--env-file", str(env_file), *arguments)


def parse_compose_override(raw: str) -> tuple[str, ...]:
    try:
        parsed = tuple(shlex.split(raw))
    except ValueError as error:
        raise ComposeConfigurationError(f"Invalid AEGISX_COMPOSE_COMMAND: {error}") from error
    if not parsed:
        raise ComposeConfigurationError("AEGISX_COMPOSE_COMMAND cannot be empty")
    return parsed


def discover_compose_providers(
    runner: CommandExecutor,
    root: Path,
    env_file: Path,
    *,
    override: str | None = None,
) -> tuple[ComposeProvider, ...]:
    configured_override = override if override is not None else os.environ.get(
        "AEGISX_COMPOSE_COMMAND"
    )
    commands = (
        (parse_compose_override(configured_override),)
        if configured_override is not None
        else (("docker", "compose"), ("podman", "compose"))
    )
    providers: list[ComposeProvider] = []
    for command in commands:
        if not runner.executable_exists(command[0]):
            continue
        provider = ComposeProvider(command)
        result = runner.run(provider.argv(env_file, "config", "--quiet"), cwd=root, timeout=30)
        if result.returncode == 0:
            providers.append(provider)
    return tuple(providers)
