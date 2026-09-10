import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    def diagnostic(self, limit: int = 500) -> str:
        text = (self.stderr.strip() or self.stdout.strip() or f"exit code {self.returncode}")
        if len(text) <= limit:
            return text
        if limit <= 3:
            return "." * max(limit, 0)
        return f"{text[: limit - 3]}..."


class CommandRunner:
    def executable_exists(self, executable: str) -> bool:
        return shutil.which(executable) is not None

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        timeout: float | None = None,
    ) -> CommandResult:
        # Commands are constructed as argv tuples by the launcher; no shell is involved.
        completed = subprocess.run(  # noqa: S603
            argv,
            cwd=cwd,
            timeout=timeout,
            check=False,
            capture_output=True,
            text=True,
        )
        return CommandResult(argv, completed.returncode, completed.stdout, completed.stderr)
